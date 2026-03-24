"""
批量 APL 函数生成器

从飞书多维表格读取「待执行」记录（描述不为空、函数名为空），
依次生成并部署 APL 函数，结果写回原记录行。

多维表格使用说明：
  1. 在现有多维表格里填写新行：
     - 「描述」列填写需求文本（支持多行，粘贴到单元格里）
     - 「绑定对象」列填写对象名称，如"客户"、"提货单"、"AccountObj"
     - 可选列：「函数类型」「trigger_type/触发类型」「项目」（写入 req，如 scheduled_task、朗润生物）
     - 「函数名」和「系统API名」留空；执行后「状态」「执行时间」「执行反馈」自动更新
  2. config.local.yml 中 feishu.bitable_app_token / bitable_table_id 指向该表（或与链接中 base、tbl 一致）
  3. 命令行：python3 batch_runner.py（无需逐条人工确认）；或飞书机器人触发同等逻辑

用法（命令行直接测试）：
  python3 batch_runner.py [--dry-run] [--regenerate] [--headed] [--bitable-app-token ...] [--bitable-table-id ...]

  --dry-run     仅打印待执行记录，不实际执行 pipeline
  --regenerate  重新生成：先清空所有有描述行的函数名/状态，再批量执行
  --headed      显示浏览器窗口（默认无头模式，不弹窗）
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import re
import time
from pathlib import Path

import yaml

from utils import (
    load_config,
    resolve_namespace,
    NAMESPACE_TO_CODE_PREFIX,
    infer_short_code_summary,
    OBJECT_LABEL_TO_API,
)

TOOLS_DIR = Path(__file__).parent


def _infer_object_api(label: str) -> tuple[str, str]:
    """根据绑定对象输入推断 (object_api, object_label)。"""
    label = label.strip()
    if not label:
        return ("", "")
    # 已经是 API 名（含 Obj 或 __c）
    if re.search(r"Obj$|__c$", label):
        # 反查中文名
        reverse = {v: k for k, v in OBJECT_LABEL_TO_API.items()}
        return (label, reverse.get(label, label))
    # 中文 → API
    api = OBJECT_LABEL_TO_API.get(label, "")
    return (api, label)


def _build_req_yml(
    desc: str,
    object_label: str,
    function_type_hint: str = "",
    trigger_type_hint: str = "",
    project_hint: str = "",
) -> str:
    """根据描述和对象标签生成 req.yml 内容。
    代码名称格式：【命名空间】+ 简短概括，如【流程】租户关联客户。"""
    object_api, object_label_clean = _infer_object_api(object_label)

    # 优先用表格里明确填写的函数类型
    func_type = "流程函数"
    namespace = "流程"
    if function_type_hint:
        from utils import FUNCTION_TYPE_ALIASES, FUNCTION_TYPE_TO_NAMESPACE
        ft = FUNCTION_TYPE_ALIASES.get(function_type_hint.strip().lower(), function_type_hint.strip())
        ns = FUNCTION_TYPE_TO_NAMESPACE.get(ft, "流程")
        func_type = ft
        namespace = ns
    elif any(kw in desc for kw in ["自定义控制器", "控制器接口", "call_controller", "接口"]):
        func_type = "自定义控制器"
        namespace = "自定义控制器"
    elif any(kw in desc for kw in ["范围规则", "范围规则函数", "关联字段", "介绍人"]):
        func_type = "范围规则"
        namespace = "范围规则"
    elif any(kw in desc for kw in ["按钮", "点击按钮", "按钮触发"]):
        func_type = "按钮函数"
        namespace = "按钮"
    elif any(kw in desc for kw in ["UI函数", "UI事件", "页面", "默认值"]):
        func_type = "UI函数"
        namespace = "UI事件"
    elif any(kw in desc for kw in ["同步前", "sync_before"]):
        func_type = "同步前函数"
        namespace = "流程"
    elif any(kw in desc for kw in ["同步后", "sync_after"]):
        func_type = "同步后函数"
        namespace = "流程"
    elif any(kw in desc for kw in ["计划任务", "定时", "cron"]):
        func_type = "计划任务"
        namespace = "计划任务"
    elif any(kw in desc for kw in ["校验", "校验函数"]):
        func_type = "校验函数"
        namespace = "校验函数"

    # 代码名称：【命名空间】+ 简短概括（如【流程】租户关联客户）
    prefix = NAMESPACE_TO_CODE_PREFIX.get(namespace, f"【{namespace}】")
    summary = infer_short_code_summary(desc, object_label_clean)
    code_name = f"{prefix}{summary}"
    print(f"  [调试] _build_req_yml: desc前20字='{desc[:20]}', summary='{summary}', code_name='{code_name}'")

    lines = [
        "requirement: |",
    ]
    for line in desc.strip().splitlines():
        lines.append(f"  {line}")
    lines += [
        f"object_api: {object_api or 'AccountObj'}",
        f"object_label: {object_label_clean or object_api or '客户'}",
        f"function_type: {func_type}",
        f"namespace: {namespace}",
        f"code_name: {code_name}",
        f"output_file: {code_name}",
        "author: 纷享实施人员",
    ]
    tt = (trigger_type_hint or "").strip()
    if tt:
        lines.append(f"trigger_type: {tt}")
    pj = (project_hint or "").strip()
    if pj:
        lines.append(f"project: {pj}")
    return "\n".join(lines) + "\n"


def _run_pipeline(req_yml_content: str) -> tuple[bool, str, str, str]:
    """
    写入临时 req.yml 并执行 pipeline.py。
    返回 (success, output, func_name, api_name)。
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", dir=TOOLS_DIR,
        prefix="batch_req_", delete=False, encoding="utf-8"
    ) as f:
        f.write(req_yml_content)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, "pipeline.py", "--req", tmp_path, "--no-feishu-log"],
            cwd=str(TOOLS_DIR),
            capture_output=True,
            text=True,
            timeout=600,  # 10分钟超时
        )
        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        success = result.returncode == 0

        # 从输出中提取函数名和 API 名
        func_name = _extract_value(output, r"\[pipeline\].*?生成.*?[：:]\s*(.+)")
        if not func_name:
            func_name = _extract_value(output, r"code_name[：:]\s*(.+)")
        api_name = _extract_value(output, r"函数 API 名.*?[：:]\s*(\w+__c)")

        return success, output, func_name.strip(), api_name.strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _extract_value(text: str, pattern: str) -> str:
    m = re.search(pattern, text)
    return m.group(1).strip() if m else ""


def run_batch_inprocess(cfg: dict, dry_run: bool = False, regenerate: bool = False, headed: bool = False) -> list[dict]:
    """批量执行：共享一个浏览器实例，任务间只需回到函数列表页，不反复开关浏览器。"""
    from playwright.sync_api import sync_playwright
    from generator.generate import generate
    from deployer.deploy import _deploy_in_page, load_func_meta
    from deployer.deploy_login import (
        ensure_logged_in_via_agent_or_manual,
        navigate_to_function_list,
        dismiss_stale_apl_modals,
        load_cookies,
        save_cookies,
    )
    from feishu_record import (
        list_bitable_pending_records, mark_bitable_record,
        clear_bitable_for_regenerate,
        append_func_to_feishu, collect_func_info,
        STATUS_RUNNING, STATUS_OK, STATUS_FAIL,
        FIELD_DESC, FIELD_OBJECT,
    )

    if regenerate:
        cleared = clear_bitable_for_regenerate(cfg)
        print(f"[批量] 重新生成模式：已清空 {cleared} 条记录的函数名/状态，即将重新执行")
        if cleared == 0:
            print("[批量] 没有可重新生成的记录（描述为空的行不参与）")
            return []

    pending = list_bitable_pending_records(cfg)
    if not pending:
        print("[批量] 没有待执行的记录")
        print("  提示：在多维表格中，需满足「描述」已填、「函数名」为空、「状态」为待执行")
        print("  若上次已生成过，请新增一行：填「描述」和「绑定对象」，函数名留空")
        return []

    print(f"[批量] 找到 {len(pending)} 条待执行记录")
    results = []

    if dry_run:
        for i, record in enumerate(pending, 1):
            desc = record[FIELD_DESC]
            obj_label = record[FIELD_OBJECT]
            req_content = _build_req_yml(desc, obj_label)
            print(f"\n[批量] [dry-run] 第 {i}/{len(pending)} 条:\n{req_content}")
            results.append({"record_id": record["record_id"], "dry_run": True})
        return results

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed, slow_mo=150)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # 登录一次，后续任务复用 session
        login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")
        has_session = load_cookies(context, cfg)
        if has_session:
            navigate_to_function_list(page, cfg)
            time.sleep(2)
            if login_path in page.url:
                print("  [批量] Session 已过期，重新登录...")
                has_session = False
            else:
                # SPA 可能 URL 不变但内容为登录页，检查是否能看到函数列表
                try:
                    page.wait_for_selector(':text("新建APL函数"), :text("新建")', timeout=20000)
                except Exception:
                    print("  [批量] 未检测到函数列表，Session 可能失效，重新登录...")
                    has_session = False
        if not has_session:
            if not ensure_logged_in_via_agent_or_manual(page, cfg):
                raise RuntimeError("登录失败或超时，请重试。")
            save_cookies(context, cfg)
            navigate_to_function_list(page, cfg)

        for i, record in enumerate(pending, 1):
            dismiss_stale_apl_modals(page)
            navigate_to_function_list(page, cfg)
            time.sleep(1.2 if i > 1 else 0.8)

            record_id = record["record_id"]
            desc = record[FIELD_DESC]
            obj_label = record[FIELD_OBJECT]
            func_type_hint = record.get("函数类型", "")
            trigger_hint = (record.get("trigger_type") or "").strip()
            project_hint = (record.get("项目") or record.get("project") or "").strip()
            tmp_path = None

            print(f"\n[批量] ── 第 {i}/{len(pending)} 条 ──")
            print(f"  描述: {desc[:60]}{'...' if len(desc) > 60 else ''}")
            print(f"  对象: {obj_label or '(未填写，将使用默认)'}")
            print(f"  函数类型: {func_type_hint or '(自动推断)'}  trigger_type: {trigger_hint or '-'}  项目: {project_hint or '-'}")

            try:
                mark_bitable_record(cfg, record_id, STATUS_RUNNING)
            except Exception as e:
                print(f"  [警告] 标记执行中失败: {e}")

            try:
                # ── 生成 APL 代码（无需浏览器）──
                req_content = _build_req_yml(
                    desc,
                    obj_label,
                    function_type_hint=func_type_hint,
                    trigger_type_hint=trigger_hint,
                    project_hint=project_hint,
                )
                req_data = yaml.safe_load(req_content)

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".yml", dir=TOOLS_DIR,
                    prefix="batch_req_", delete=False, encoding="utf-8"
                ) as f:
                    f.write(req_content)
                    tmp_path = f.name

                print(f"  [批量] 生成代码中...")
                # 抓取字段（含从需求推断的关联对象）；传 page 复用浏览器，缓存命中时无额外开销
                try:
                    from fetcher.fetch_fields import fetch_fields_for_req
                    fields_map = fetch_fields_for_req(req_data, cfg, page=page) or {}
                except Exception as e:
                    print(f"  [批量] 字段抓取跳过: {e}")
                    fields_map = {}
                apl_file = str(
                    generate(req_data, cfg, fields_map=fields_map, req_file_path=tmp_path)
                )
                func_name = Path(apl_file).stem

                # ── 部署（复用已有浏览器，回到函数列表即可）──
                namespace = resolve_namespace(req_data)
                object_label = req_data.get("object_label", "")
                raw_req = req_data.get("requirement", "") or ""
                description_text = raw_req.strip().splitlines()[0][:100] if raw_req.strip() else ""

                print(f"  [批量] 部署中: {func_name}")
                ok = _deploy_in_page(
                    page, apl_file, func_name, cfg,
                    namespace=namespace, object_label=object_label,
                    description=description_text, req=req_data,
                    ensure_login=False,   # 已在循环外登录，只需导航
                )

                # 从 meta 文件读取系统 API 名
                meta = load_func_meta(apl_file)
                func_api_name = meta.get("func_api_name", "")

                if ok:
                    fb = f"已生成并部署。系统API: {func_api_name or '见纷享'}。本地文件: {apl_file}"
                    mark_bitable_record(
                        cfg, record_id, STATUS_OK,
                        func_name=func_name, api_name=func_api_name, feedback=fb,
                    )
                    print(f"  ✅ 成功: {func_name} ({func_api_name})")
                    results.append({
                        "record_id": record_id, "desc": desc[:40],
                        "success": True, "func_name": func_name, "api_name": func_api_name,
                    })
                else:
                    mark_bitable_record(
                        cfg, record_id, STATUS_FAIL,
                        error="部署步骤返回失败（编译未通过或浏览器流程中断），请查看 _tools 终端完整日志",
                    )
                    print(f"  ❌ 失败: 部署步骤返回 False")
                    results.append({
                        "record_id": record_id, "desc": desc[:40],
                        "success": False, "func_name": func_name, "api_name": "",
                    })

            except Exception as e:
                err_msg = str(e)[:80]
                try:
                    mark_bitable_record(cfg, record_id, STATUS_FAIL, error=err_msg)
                except Exception:
                    pass
                print(f"  ❌ 异常: {err_msg}")
                results.append({
                    "record_id": record_id, "desc": desc[:40],
                    "success": False, "func_name": "", "api_name": "",
                })
            finally:
                if tmp_path:
                    Path(tmp_path).unlink(missing_ok=True)
                try:
                    dismiss_stale_apl_modals(page)
                except Exception:
                    pass

        save_cookies(context, cfg)
        browser.close()

    return results


def run_batch(cfg: dict, dry_run: bool = False, regenerate: bool = False, headed: bool = False) -> list[dict]:
    """批量生成主入口，使用共享浏览器模式提升效率。"""
    return run_batch_inprocess(cfg, dry_run=dry_run, regenerate=regenerate, headed=headed)


def print_summary(results: list[dict]) -> str:
    """打印并返回摘要文本，供机器人发回飞书。"""
    if not results:
        return "没有待执行的记录。\n\n提示：在多维表格「描述」列填写需求，「函数名」留空，再发送「批量生成」。"

    lines = [f"批量执行完成，共 {len(results)} 条：\n"]
    ok = [r for r in results if r.get("success")]
    fail = [r for r in results if not r.get("success") and not r.get("dry_run")]

    for r in results:
        if r.get("dry_run"):
            lines.append(f"  📋 [dry-run] {r['record_id']}")
        elif r.get("success"):
            lines.append(f"  ✅ {r['func_name'] or r['desc']} → {r['api_name'] or '(API名待确认)'}")
        else:
            lines.append(f"  ❌ {r['desc']} → 失败")

    lines.append(f"\n成功 {len(ok)} / 失败 {len(fail)} / 共 {len(results)}")
    summary = "\n".join(lines)
    print(summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description="批量 APL 函数生成器")
    parser.add_argument("--dry-run", action="store_true", help="仅预览待执行记录，不实际执行")
    parser.add_argument("--regenerate", action="store_true",
                        help="重新生成：先清空所有有描述行的函数名/状态，再批量执行")
    parser.add_argument("--headed", action="store_true",
                        help="显示浏览器窗口（默认无头模式，不弹窗）")
    parser.add_argument("--config", default=None, help="config 文件路径")
    parser.add_argument("--bitable-app-token", dest="bitable_app_token", default=None,
                        help="覆盖 config 中的多维表格 app_token")
    parser.add_argument("--bitable-table-id", dest="bitable_table_id", default=None,
                        help="覆盖 config 中的多维表格 table_id")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.bitable_app_token or args.bitable_table_id:
        cfg.setdefault("feishu", {})
        if args.bitable_app_token:
            cfg["feishu"]["bitable_app_token"] = args.bitable_app_token.strip()
        if args.bitable_table_id:
            cfg["feishu"]["bitable_table_id"] = args.bitable_table_id.strip()
    results = run_batch(cfg, dry_run=args.dry_run, regenerate=args.regenerate, headed=args.headed)
    summary = print_summary(results)

    # 批量完成后直接推送飞书通知，不依赖 agent 回复
    if not args.dry_run:
        try:
            from feishu_record import send_feishu_notify
            send_feishu_notify(summary, cfg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
