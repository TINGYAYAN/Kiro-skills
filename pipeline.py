"""
APL 自动化流水线主入口

用法：
  # 抓取字段 API 名（首次或刷新缓存时使用）
  python pipeline.py --req req.yml --step fetch

  # 仅生成 APL 代码（自动读取字段缓存）
  python pipeline.py --req req.yml --step generate

  # 生成 + 浏览器部署
  python pipeline.py --req req.yml --step deploy

  # 生成 + 部署 + 自动测试（完整流水线）
  python pipeline.py --req req.yml --step all

  # 仅部署（已有 APL 文件）
  python pipeline.py --file my_func.apl --func-name "函数名" --step deploy

  # 仅测试
  python pipeline.py --case tester/cases/example.yml --step test

req.yml 格式参考 generator/generate.py 文档注释。
related_objects 示例（可选，指定关联对象以抓取其字段）：
  related_objects:
    - api: AccountObj
      label: 客户
"""
import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from utils import (
    load_config,
    resolve_namespace,
    cleanup_runtime_artifacts,
    sync_function_type_from_trigger_type,
    infer_function_type_into_req_if_missing,
)


def _fetch_validated_fields(req: dict, cfg: dict, *, force_refresh: bool, page=None) -> dict:
    from fetcher.fetch_fields import fetch_fields_for_req, find_incomplete_option_values

    fields_map = fetch_fields_for_req(req, cfg, force_refresh=force_refresh, page=page)
    issues = find_incomplete_option_values(fields_map or {}, req)
    if issues:
        detail = "；".join(
            f"{i.get('object_label') or i.get('object_api')}."
            f"{i.get('field_label') or i.get('field_api')}"
            f" 缺少选项值: {', '.join(i.get('option_labels') or [])}"
            for i in issues
        )
        warning = (
            "字段选项值不完整，但继续生成："
            + detail
            + "。生成代码时会尽量保留注释/TODO，后续可人工调整。"
        )
        req["_field_warning"] = warning
        print(f"[pipeline] ⚠ {warning}")
    return fields_map or {}


def step_fetch(args, cfg) -> dict:
    """抓取 req.yml 中所有对象的字段 API 名并缓存，返回 {object_api: [fields]}。"""
    if not args.req:
        sys.exit("[pipeline] --step fetch 需要提供 --req 文件")

    import yaml
    req = yaml.safe_load(Path(args.req).read_text(encoding="utf-8")) or {}
    print("\n" + "="*50)
    print("步骤 0/3  抓取字段 API 名")
    print("="*50)
    started = time.perf_counter()
    force = getattr(args, "force_fetch", False)
    fields_map = _fetch_validated_fields(req, cfg, force_refresh=force)
    total = sum(len(v) for v in fields_map.values())
    print(f"[pipeline] 字段抓取完成，共 {len(fields_map)} 个对象、{total} 个字段")
    print(f"[耗时] 字段抓取: {time.perf_counter() - started:.1f}s")
    return fields_map


def step_generate(args, cfg, fields_map: dict = None) -> str:
    """执行生成步骤，返回生成的 APL 文件路径。"""
    if not args.req:
        sys.exit("[pipeline] --step generate 需要提供 --req 文件")

    import yaml
    from generator.generate import generate

    req = yaml.safe_load(Path(args.req).read_text(encoding="utf-8"))

    # 若没有传入 fields_map，尝试从缓存读取
    if fields_map is None:
        try:
            fields_map = _fetch_validated_fields(req, cfg, force_refresh=False)
            if fields_map:
                total = sum(len(v) for v in fields_map.values())
                print(f"[pipeline] 已从缓存加载字段信息：{len(fields_map)} 个对象，{total} 个字段")
        except Exception as e:
            print(f"[pipeline] 字段缓存读取失败（跳过）: {e}")
            fields_map = {}

    print("\n" + "="*50)
    print("步骤 1/3  生成 APL 代码")
    print("="*50)
    started = time.perf_counter()
    out_path = generate(
        req, cfg, fields_map=fields_map or {}, req_file_path=args.req
    )
    print(f"[耗时] 生成代码: {time.perf_counter() - started:.1f}s")
    return str(out_path)


def step_deploy(apl_file: str, func_name: str, args, cfg, req: dict = None,
                fields_map_snapshot = None) :
    """执行部署步骤，返回是否成功。"""
    from deployer.deploy import deploy

    headless = getattr(args, "headless", False)
    update   = getattr(args, "update", False)
    from utils import sync_function_type_from_trigger_type, infer_function_type_into_req_if_missing
    sync_function_type_from_trigger_type(req or {})
    infer_function_type_into_req_if_missing(req or {})
    namespace = resolve_namespace(req or {})
    object_label = (req or {}).get("object_label", "")
    # 用 requirement 第一行作为描述，不超过100字
    raw_req = (req or {}).get("requirement", "") or ""
    description = raw_req.strip().splitlines()[0][:100] if raw_req.strip() else ""
    print("\n" + "="*50)
    print("步骤 2/3  部署到纷享销客")
    print("="*50)
    started = time.perf_counter()
    func_api_name = getattr(args, "func_api_name", "") or ((req or {}).get("func_api_name") or "")
    result = deploy(apl_file, func_name, cfg, headless=headless, update=update,
                  namespace=namespace, object_label=object_label, description=description,
                  req=req, func_api_name=func_api_name, fields_map_snapshot=fields_map_snapshot)
    print(f"[耗时] 浏览器部署: {time.perf_counter() - started:.1f}s")
    return result


def _summarize_predeploy_compile(apl_file: str, func_name: str, cfg: dict, req: Optional[dict] = None) -> dict:
    from deployer.deploy import inspect_runtime_precheck
    code = Path(apl_file).read_text(encoding="utf-8")
    return inspect_runtime_precheck(code, cfg=cfg, req=req or {}, func_name=func_name)


def step_test(case_file: str, args, cfg) :
    """执行测试步骤，返回是否全部通过。"""
    from tester.test_runner import run

    do_teardown = not getattr(args, "no_teardown", False)
    print("\n" + "="*50)
    print("步骤 3/3  自动化测试")
    print("="*50)
    started = time.perf_counter()
    results = run(case_file, cfg, do_teardown=do_teardown)
    print(f"[耗时] 自动化测试: {time.perf_counter() - started:.1f}s")
    return all(r["failed"] == 0 for r in results)


def resolve_func_name(args, apl_file: str) -> str:
    """从参数或文件名解析函数名。"""
    if getattr(args, "func_name", None):
        return args.func_name
    # 从文件名推断（去掉扩展名）
    return Path(apl_file).stem


def main():
    parser = argparse.ArgumentParser(
        description="APL 自动化流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step",
        choices=["fetch", "generate", "deploy", "test", "all"],
        default="all",
        help="执行步骤: fetch|generate|deploy|test|all (默认: all)",
    )
    parser.add_argument("--force-fetch", dest="force_fetch", action="store_true",
                        help="强制刷新字段缓存（配合 --step fetch 使用）")
    parser.add_argument("--no-refresh", dest="no_refresh", action="store_true",
                        help="跳过实时拉取，使用本地字段缓存")
    parser.add_argument("--req", help="需求 YAML 文件路径（generate 步骤必填）")
    parser.add_argument("--project", "-p", help="项目名；指定时默认用 sharedev_pull/{项目}/req.yml 作为 --req")
    parser.add_argument("--file", help="已有 APL 文件路径（跳过 generate 步骤时使用）")
    parser.add_argument("--func-name", dest="func_name", help="纷享销客中的函数名称（deploy 步骤）")
    parser.add_argument("--case", help="测试用例 YAML 文件路径（test 步骤）")
    parser.add_argument("--headless", action="store_true", help="无头模式运行浏览器")
    parser.add_argument("--update", action="store_true",
                        help="需求变更/修改模式：按 func_api_name 搜索后编辑，在现有函数基础上修改")
    parser.add_argument("--func-api-name", dest="func_api_name", default="",
                        help="更新模式时必填：系统函数 API 名，如 Proc_XXX__c")
    parser.add_argument("--no-teardown", dest="no_teardown", action="store_true",
                        help="测试后不清理数据")
    parser.add_argument("--config", default=None, help="config 文件路径")
    parser.add_argument("--no-feishu-log", dest="no_feishu_log", action="store_true",
                        help="跳过部署后的飞书多维表格记录（批量模式由 batch_runner 自行写回）")
    parser.add_argument("--no-notify", dest="no_notify", action="store_true",
                        help="跳过私聊/群聊通知，仅本地执行（调试回归用）")
    parser.add_argument("--runtime-precheck", dest="runtime_precheck", action="store_true",
                        help="部署前调用系统 runtime/debug 预检编译错误（默认关闭，不影响原流程）")
    parser.add_argument("--web-create-api", dest="web_create_api", action="store_true",
                        help="新建函数时优先走 Web Session create 接口（默认关闭，失败回退浏览器）")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if getattr(args, "runtime_precheck", False):
        cfg.setdefault("deployer", {})
        cfg["deployer"]["runtime_debug_precheck"] = True
    if getattr(args, "web_create_api", False):
        cfg.setdefault("deployer", {})
        cfg["deployer"]["web_create_api"] = True
    try:
        cleanup = cleanup_runtime_artifacts()
        if cleanup.get("cleaned_temp") or cleanup.get("archived_reports"):
            print(
                f"[pipeline] 已清理临时文件 {cleanup.get('cleaned_temp', 0)} 个，"
                f"归档修复报告 {cleanup.get('archived_reports', 0)} 个"
            )
    except Exception:
        pass
    step = args.step

    # 若指定了 --project 且未显式传入 --req，默认使用 sharedev_pull/{项目}/req.yml。
    # 一旦调用方已经明确给了 --req（哪怕文件名就叫 req.yml），都必须尊重该输入，
    # 不能再悄悄切回项目目录里的旧 req，否则会出现“展示的是新需求，实际执行的是旧项目 req”的串单。
    req_path = getattr(args, "req", None)
    if getattr(args, "project", None):
        proj_req = Path(__file__).parent / "sharedev_pull" / args.project.strip() / "req.yml"
        if not req_path and proj_req.exists():
            args.req = str(proj_req)
            req_path = args.req
            print(f"[pipeline] 使用项目 req: {proj_req}")

    apl_file = getattr(args, "file", None)
    success = True
    fields_map_for_gen = None

    # 预加载 req.yml（用于 generate 和 deploy 两步）
    req = {}
    if getattr(args, "req", None):
        import yaml
        req = yaml.safe_load(Path(args.req).read_text(encoding="utf-8")) or {}
        sync_function_type_from_trigger_type(req)
        infer_function_type_into_req_if_missing(req)
        print(
            f"[pipeline] 执行快照: req={Path(args.req).resolve()} | "
            f"function_type={req.get('function_type') or '-'} | "
            f"namespace={resolve_namespace(req)} | "
            f"object={req.get('object_label') or req.get('object_api') or '-'}"
        )
    elif getattr(args, "file", None):
        req_path = Path(args.file).parent / "req.yml"
        if req_path.exists():
            import yaml
            req = yaml.safe_load(req_path.read_text(encoding="utf-8")) or {}
            if req:
                print(f"[pipeline] 已从同目录加载 req.yml: {req_path}")
                sync_function_type_from_trigger_type(req)
                infer_function_type_into_req_if_missing(req)

    from feishu_record import send_feishu_notify

    func_name_hint = req.get("code_name") or (Path(apl_file).stem if apl_file else "")

    # ---- fetch ----
    if step == "fetch":
        step_fetch(args, cfg)
        print("\n[pipeline] 字段抓取完成。可运行 --step generate 生成代码。")
        sys.exit(0)

    # ---- generate ----
    if step in ("generate", "deploy", "all"):
        if step == "generate" or (step in ("deploy", "all") and not apl_file):
            if not getattr(args, "no_notify", False):
                send_feishu_notify(f"🤖 开始生成 APL 代码：{func_name_hint}", cfg)
            fields_map_for_gen = None
            if step in ("deploy", "all") and req:
                try:
                    force = not getattr(args, "no_refresh", False)
                    prefetch_started = time.perf_counter()
                    fields_map_for_gen = _fetch_validated_fields(req, cfg, force_refresh=force)
                    if fields_map_for_gen:
                        total = sum(len(v) for v in fields_map_for_gen.values())
                        print(f"[pipeline] 预拉取字段：{len(fields_map_for_gen)} 个对象、{total} 个字段")
                    print(f"[耗时] 预拉取字段: {time.perf_counter() - prefetch_started:.1f}s")
                except Exception as e:
                    print(f"[pipeline] 预拉取字段失败（将用缓存或部署时抓取）: {e}")
                    fields_map_for_gen = {}
            apl_file = step_generate(args, cfg, fields_map=fields_map_for_gen or None)
            func_name_hint = Path(apl_file).stem

    # ---- deploy ----
    if step in ("deploy", "all"):
        if not apl_file:
            sys.exit("[pipeline] deploy 步骤需要 --file 或先执行 generate 步骤")
        if fields_map_for_gen is None and req:
            try:
                prefetch_started = time.perf_counter()
                fields_map_for_gen = _fetch_validated_fields(
                    req, cfg, force_refresh=not getattr(args, "no_refresh", False)
                )
                print(f"[耗时] 部署前字段预取: {time.perf_counter() - prefetch_started:.1f}s")
            except Exception as e:
                print(f"[pipeline] 部署前字段预取失败（将沿用旧行为）: {e}")
                fields_map_for_gen = {}
        func_name = resolve_func_name(args, apl_file)
        predeploy_compile = None
        try:
            predeploy_compile = _summarize_predeploy_compile(apl_file, func_name, cfg, req=req)
            print(f"[pipeline] {predeploy_compile['message']}")
        except Exception as e:
            predeploy_compile = {
                "enabled": True,
                "status": "transport_error",
                "message": f"本地编译预检调用失败：{e}",
            }
            print(f"[pipeline] {predeploy_compile['message']}")
        if not getattr(args, "no_notify", False):
            compile_msg = predeploy_compile["message"] if predeploy_compile else "本地编译预检未执行"
            send_feishu_notify(
                f"🌐 代码生成完成。\n{compile_msg}\n开始部署「{func_name}」到纷享销客...",
                cfg,
            )
        ok = step_deploy(apl_file, func_name, args, cfg, req=req, fields_map_snapshot=fields_map_for_gen)
        if not ok:
            if not getattr(args, "no_notify", False):
                send_feishu_notify(f"❌ 部署失败：{func_name}，请查看日志", cfg)
            print("[pipeline] 部署失败，中止流水线")
            sys.exit(1)

        # 部署成功后：统一诊断
        try:
            from deployer.post_deploy import summarize_post_deploy
            fm = fields_map_for_gen or {}
            if not fm and req:
                fm = _fetch_validated_fields(req, cfg, force_refresh=False)
            diag = summarize_post_deploy(apl_file, fm, req)
            for warning in diag.get("warnings") or []:
                print(f"[pipeline] ⚠ {warning}")
            cr = diag.get("credibility")
            if cr:
                print(f"\n[pipeline] {cr['summary']}")
                if not cr["credible"] and cr["used_unknown"]:
                    if not getattr(args, "no_notify", False):
                        send_feishu_notify(
                            f"⚠ 字段可信度：存在未确认字段 {', '.join(cr['used_unknown'][:3])}，建议人工核查",
                            cfg,
                        )
        except Exception as e:
            print(f"\n[pipeline] 可信度校验跳过: {e}")

        # 部署成功后，若配置了飞书多维表格，则追加记录（批量模式由 batch_runner 自行写回，跳过此步）
        doc_url = None
        if not getattr(args, "no_feishu_log", False):
            try:
                from deployer.deploy import load_func_meta
                from feishu_record import append_func_to_feishu, collect_func_info
                meta = load_func_meta(apl_file)
                info = collect_func_info(apl_file, req, meta)
                doc_url = append_func_to_feishu(
                    info["func_name"],
                    info["description"],
                    info["object_label"],
                    info["func_api_name"],
                    cfg,
                )
                if doc_url:
                    print(f"\n[pipeline] 已记录到飞书多维表格: {doc_url}")
            except Exception as e:
                feishu = (cfg.get("feishu") or {})
                has_conf = feishu.get("spreadsheet_token") or (
                    feishu.get("bitable_app_token") and feishu.get("bitable_table_id")
                )
                if has_conf:
                    print(f"\n[pipeline] 飞书记录失败（可忽略）: {e}")

        api_name = (req or {}).get("func_api_name", "")
        msg = f"✅ 部署成功：{func_name}"
        if api_name:
            msg += f"\nAPI名：{api_name}"
        if doc_url:
            msg += f"\n记录：{doc_url}"
        if not getattr(args, "no_notify", False):
            send_feishu_notify(msg, cfg)

    # ---- test ----
    if step in ("test", "all"):
        case_file = getattr(args, "case", None)
        if not case_file:
            if apl_file:
                stem = Path(apl_file).stem
                auto = Path(__file__).parent / "tester" / "cases" / f"{stem}.yml"
                if auto.exists():
                    case_file = str(auto)
                    print(f"[pipeline] 自动使用测试用例: {case_file}")
        if not case_file:
            print("[pipeline] 未指定 --case，跳过测试步骤")
        else:
            ok = step_test(case_file, args, cfg)
            success = ok

    print("\n[pipeline] 流水线执行完成")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
