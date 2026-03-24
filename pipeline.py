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
from pathlib import Path

from utils import load_config, resolve_namespace


def step_fetch(args, cfg) -> dict:
    """抓取 req.yml 中所有对象的字段 API 名并缓存，返回 {object_api: [fields]}。"""
    if not args.req:
        sys.exit("[pipeline] --step fetch 需要提供 --req 文件")

    import yaml
    from fetcher.fetch_fields import fetch_fields_for_req

    req = yaml.safe_load(Path(args.req).read_text(encoding="utf-8")) or {}
    print("\n" + "="*50)
    print("步骤 0/3  抓取字段 API 名")
    print("="*50)
    force = getattr(args, "force_fetch", False)
    fields_map = fetch_fields_for_req(req, cfg, force_refresh=force)
    total = sum(len(v) for v in fields_map.values())
    print(f"[pipeline] 字段抓取完成，共 {len(fields_map)} 个对象、{total} 个字段")
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
            from fetcher.fetch_fields import fetch_fields_for_req
            fields_map = fetch_fields_for_req(req, cfg, force_refresh=True)
            if fields_map:
                total = sum(len(v) for v in fields_map.values())
                print(f"[pipeline] 已从缓存加载字段信息：{len(fields_map)} 个对象，{total} 个字段")
        except Exception as e:
            print(f"[pipeline] 字段缓存读取失败（跳过）: {e}")
            fields_map = {}

    print("\n" + "="*50)
    print("步骤 1/3  生成 APL 代码")
    print("="*50)
    out_path = generate(
        req, cfg, fields_map=fields_map or {}, req_file_path=args.req
    )
    return str(out_path)


def step_deploy(apl_file: str, func_name: str, args, cfg, req: dict = None) -> bool:
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
    func_api_name = getattr(args, "func_api_name", "") or ((req or {}).get("func_api_name") or "")
    return deploy(apl_file, func_name, cfg, headless=headless, update=update,
                  namespace=namespace, object_label=object_label, description=description,
                  req=req, func_api_name=func_api_name)


def step_test(case_file: str, args, cfg) -> bool:
    """执行测试步骤，返回是否全部通过。"""
    from tester.test_runner import run

    do_teardown = not getattr(args, "no_teardown", False)
    print("\n" + "="*50)
    print("步骤 3/3  自动化测试")
    print("="*50)
    results = run(case_file, cfg, do_teardown=do_teardown)
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
    args = parser.parse_args()

    cfg = load_config(args.config)
    step = args.step

    # 若指定了 --project 且（未指定 --req 或 --req 为 req.yml），用 sharedev_pull/{项目}/req.yml
    req_path = getattr(args, "req", None)
    if getattr(args, "project", None):
        proj_req = Path(__file__).parent / "sharedev_pull" / args.project.strip() / "req.yml"
        if (not req_path or Path(req_path).name == "req.yml") and proj_req.exists():
            args.req = str(proj_req)
            req_path = args.req
            print(f"[pipeline] 使用项目 req: {proj_req}")

    apl_file = getattr(args, "file", None)
    success = True

    # 预加载 req.yml（用于 generate 和 deploy 两步）
    req = {}
    if getattr(args, "req", None):
        import yaml
        req = yaml.safe_load(Path(args.req).read_text(encoding="utf-8")) or {}
    elif getattr(args, "file", None):
        req_path = Path(args.file).parent / "req.yml"
        if req_path.exists():
            import yaml
            req = yaml.safe_load(req_path.read_text(encoding="utf-8")) or {}
            if req:
                print(f"[pipeline] 已从同目录加载 req.yml: {req_path}")

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
            send_feishu_notify(f"🤖 开始生成 APL 代码：{func_name_hint}", cfg)
            fields_map_for_gen = None
            if step in ("deploy", "all") and req:
                try:
                    from fetcher.fetch_fields import fetch_fields_for_req
                    force = not getattr(args, "no_refresh", False)
                    fields_map_for_gen = fetch_fields_for_req(req, cfg, force_refresh=force)
                    if fields_map_for_gen:
                        total = sum(len(v) for v in fields_map_for_gen.values())
                        print(f"[pipeline] 预拉取字段：{len(fields_map_for_gen)} 个对象、{total} 个字段")
                except Exception as e:
                    print(f"[pipeline] 预拉取字段失败（将用缓存或部署时抓取）: {e}")
                    fields_map_for_gen = {}
            apl_file = step_generate(args, cfg, fields_map=fields_map_for_gen or None)
            func_name_hint = Path(apl_file).stem

    # ---- deploy ----
    if step in ("deploy", "all"):
        if not apl_file:
            sys.exit("[pipeline] deploy 步骤需要 --file 或先执行 generate 步骤")
        func_name = resolve_func_name(args, apl_file)
        send_feishu_notify(f"🌐 代码生成完成，开始部署「{func_name}」到纷享销客...", cfg)
        ok = step_deploy(apl_file, func_name, args, cfg, req=req)
        if not ok:
            send_feishu_notify(f"❌ 部署失败：{func_name}，请查看日志", cfg)
            print("[pipeline] 部署失败，中止流水线")
            sys.exit(1)

        # 部署成功后：可信度校验
        try:
            from deployer.credibility import check_credibility
            fm = {}
            if req:
                from fetcher.fetch_fields import fetch_fields_for_req
                fm = fetch_fields_for_req(req, cfg, force_refresh=False) or {}
            if fm:
                cr = check_credibility(apl_file, fm, req)
                print(f"\n[pipeline] {cr['summary']}")
                if not cr["credible"] and cr["used_unknown"]:
                    send_feishu_notify(f"⚠ 字段可信度：存在未确认字段 {', '.join(cr['used_unknown'][:3])}，建议人工核查", cfg)
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
