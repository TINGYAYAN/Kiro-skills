"""
批量 APL 函数生成器

从飞书多维表格读取「待执行」记录（描述不为空、系统API名为空），
依次生成并部署 APL 函数，结果写回原记录行。
每条记录都会在独立浏览器上下文中执行；上一条若卡在编辑器/备注弹窗/关闭确认，不会污染下一条。
自动多轮重试时仍复用同一个 Playwright 进程，但每条记录结束后都会重建浏览器态，稳定性优先于极限速度。

多维表格使用说明：
  1. 批量生成是**基于飞书多维表格模板驱动**的；推荐先按模板建表，再让用户逐行填写
  2. 在现有多维表格里填写新行：
     - 必填列：「描述」列填写需求文本（支持多行，粘贴到单元格里）
     - 推荐列：「绑定对象」列填写对象名称，如"客户"、"提货单"、"AccountObj"
     - 推荐列：「函数类型」「trigger_type/触发类型」「项目」（写入 req，如 scheduled_task、朗润生物）
     - 「系统API名」必须留空；系统据此识别为待执行
     - 「函数名」可为空，也可能是预生成/历史残留；不再作为待执行判断依据
     - 执行后「状态」「执行时间」「执行反馈」「风险级别」「人工处理建议」自动更新
  2. config.local.yml 中 feishu.bitable_app_token / bitable_table_id 指向该表（或与链接中 base、tbl 一致）
  3. 命令行：python3 batch_runner.py（无需逐条人工确认）；或飞书机器人触发同等逻辑

推荐模板列（按顺序建表更方便）：
  描述 | 绑定对象 | 函数类型 | 项目 | 函数名 | 系统API名 | 状态 | 执行时间 | 执行反馈 | 风险级别 | 人工处理建议

用法（命令行直接测试）：
  python3 batch_runner.py [--dry-run] [--regenerate] [--headless] [--bitable-app-token ...]

  --dry-run     仅打印待执行记录，不实际执行 pipeline
  --regenerate  重新生成：先清空所有有描述行的函数名/系统API名/状态，再批量执行
  --headless    无头浏览器；默认与 pipeline 相同为「有界面」，纷享 SPA 在无头下易超时失败
  --headed      兼容旧参数，等同默认有界面（可省略）
  --no-refresh  字段仅用本地缓存，不强制从平台重拉（与 pipeline 的 --no-refresh 一致；默认会及时拉取）
  --no-retry    只跑一轮；默认只要本轮有失败会自动再跑待执行行（最多共 4 轮，无需手点）
"""
from __future__ import annotations

import argparse
import atexit
import os
import subprocess
import sys
import tempfile
import re
import time
import traceback
from pathlib import Path

import yaml

from utils import (
    load_config,
    resolve_namespace,
    NAMESPACE_TO_CODE_PREFIX,
    infer_short_code_summary,
    OBJECT_LABEL_TO_API,
    resolve_object_api_for_project,
    sync_function_type_from_trigger_type,
    infer_function_type_into_req_if_missing,
    cleanup_runtime_artifacts,
)

# 飞书「执行反馈」列长度上限（略小于 2000 留出余量）
FEISHU_FEEDBACK_MAX = 1900

# 默认自动重试失败行时，除首轮外最多再跑几轮（含首轮共 1+ 该值）
MAX_RETRY_EXTRA_PASSES = 3

TOOLS_DIR = Path(__file__).parent
LOCK_FILE = TOOLS_DIR / ".batch.lock"


def _normalize_function_type(function_type_hint: str) -> str:
    raw = (function_type_hint or "").strip()
    if not raw:
        return ""
    from utils import FUNCTION_TYPE_ALIASES
    return FUNCTION_TYPE_ALIASES.get(raw.lower(), raw)


def _function_requires_binding_object(function_type_hint: str) -> bool:
    func_type = _normalize_function_type(function_type_hint)
    return func_type not in {"自定义控制器", "计划任务"}


def _acquire_batch_lock() -> None:
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        pid_text = ""
        try:
            pid_text = LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid_text:
                os.kill(int(pid_text), 0)
                raise RuntimeError(f"批量任务正在运行中 (PID={pid_text})，请稍后再试")
        except ProcessLookupError:
            LOCK_FILE.unlink(missing_ok=True)
            return _acquire_batch_lock()
        except ValueError:
            LOCK_FILE.unlink(missing_ok=True)
            return _acquire_batch_lock()
        raise RuntimeError(f"批量锁文件存在，无法确认状态: {pid_text or str(LOCK_FILE)}")

    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))

    def _cleanup() -> None:
        try:
            if LOCK_FILE.exists() and LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
                LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)


def _infer_object_api(label: str, project_name: str = "") -> tuple[str, str]:
    """根据绑定对象输入推断 (object_api, object_label)。有项目名时优先用 sharedev objects.json，避免销售订单等全局映射与租户不一致。"""
    label = label.strip()
    if not label:
        return ("", "")
    # 已经是 API 名（含 Obj 或 __c）
    if re.search(r"Obj$|__c$", label):
        # 反查中文名
        reverse = {v: k for k, v in OBJECT_LABEL_TO_API.items()}
        return (label, reverse.get(label, label))
    resolved = resolve_object_api_for_project(label, project_name)
    if resolved:
        return (resolved, label)
    api = OBJECT_LABEL_TO_API.get(label, "")
    return (api, label)


def _build_req_yml(
    desc: str,
    object_label: str,
    function_type_hint: str = "",
    trigger_type_hint: str = "",
    project_hint: str = "",
    object_resolve_project: str = "",
) -> str:
    """根据描述和对象标签生成 req.yml 内容。
    代码名称格式：【命名空间】+ 简短概括，如【流程】租户关联客户。"""
    # 优先用表格里明确填写的函数类型
    func_type = "流程函数"
    namespace = "流程"
    if function_type_hint:
        from utils import FUNCTION_TYPE_TO_NAMESPACE
        ft = _normalize_function_type(function_type_hint)
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

    object_label_raw = object_label.strip()
    object_api, object_label_clean = _infer_object_api(
        object_label_raw, project_name=(object_resolve_project or "").strip()
    )
    if object_label_raw and not object_api:
        raise ValueError(
            f"未识别绑定对象「{object_label_raw}」。请在飞书表里填写准确对象中文名或 API 名。"
        )
    if _function_requires_binding_object(func_type):
        if not object_label_raw:
            raise ValueError(
                f"函数类型「{func_type}」必须填写绑定对象。请补充飞书表的「绑定对象」列。"
            )
        if not object_api:
            raise ValueError(
                f"函数类型「{func_type}」无法解析绑定对象「{object_label_raw}」。"
            )

    # 代码名称：【命名空间】+ 简短概括（如【流程】租户关联客户）
    prefix = NAMESPACE_TO_CODE_PREFIX.get(namespace, f"【{namespace}】")
    summary = infer_short_code_summary(desc, object_label_clean)
    code_name = f"{prefix}{summary}"

    lines = [
        "requirement: |",
    ]
    for line in desc.strip().splitlines():
        lines.append(f"  {line}")
    lines += [
        f'object_api: "{object_api or ""}"',
        f'object_label: "{object_label_clean or ""}"',
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


def _format_incomplete_option_issues(issues: list[dict]) -> str:
    parts = []
    for issue in issues:
        parts.append(
            f"{issue.get('object_label') or issue.get('object_api')}."
            f"{issue.get('field_label') or issue.get('field_api')}"
            f" 缺少选项值: {', '.join(issue.get('option_labels') or [])}"
        )
    return "；".join(parts)


def _load_fields_map_for_req(
    req_data: dict,
    cfg: dict,
    *,
    force_refresh: bool,
    page,
    field_snapshot_cache: dict[tuple[str, str], list],
) -> dict:
    from fetcher.fetch_fields import (
        _project_from_cfg,
        collect_req_object_targets,
        fetch_fields,
        find_incomplete_option_values,
    )

    project_name = (req_data.get("project") or _project_from_cfg(cfg) or "").strip()
    namespace = req_data.get("namespace", "流程")
    fields_map: dict = {}

    for target in collect_req_object_targets(req_data, cfg):
        obj_api = (target.get("api") or "").strip()
        obj_label = (target.get("label") or "").strip()
        if not obj_api or not obj_label:
            continue
        cache_key = (project_name, obj_api)
        if cache_key in field_snapshot_cache:
            fields = field_snapshot_cache[cache_key]
            print(f"  [字段抓取] 复用本轮缓存 {obj_api}: {len(fields)} 个字段")
        else:
            fields = fetch_fields(
                obj_api,
                obj_label,
                cfg,
                namespace=namespace,
                force_refresh=force_refresh,
                project_name=project_name or None,
                page=page,
            ) or []
            if fields:
                field_snapshot_cache[cache_key] = fields
        if fields:
            fields_map[obj_api] = fields

    issues = find_incomplete_option_values(fields_map, req_data)
    if issues:
        warning = (
            "字段选项值不完整，但继续生成："
            + _format_incomplete_option_issues(issues)
            + "。生成代码时会保留注释/TODO，后续可人工调整。"
        )
        req_data["_field_warning"] = warning
        print(f"  [批量] ⚠ {warning}")
    return fields_map


def _filter_pending_by_project(pending: list[dict], project_name: str) -> list[dict]:
    project = (project_name or "").strip()
    if not project:
        return pending
    out: list[dict] = []
    for record in pending:
        record_project = (record.get("项目") or record.get("project") or "").strip()
        if record_project == project:
            out.append(record)
    return out


def _batch_playwright_launch_kw(headless: bool) -> dict:
    kw: dict = {"headless": headless, "slow_mo": 50 if headless else 80}
    if headless:
        kw["args"] = ["--disable-dev-shm-usage", "--no-sandbox"]
    return kw


def _dispose_batch_browser(browser) -> None:
    if browser is None:
        return
    try:
        browser.close()
    except Exception:
        pass


def _reset_batch_browser_state(browser, context, cfg: dict):
    """每条记录结束后销毁当前浏览器态，避免旧弹窗/旧编辑器污染下一条。"""
    from deployer.deploy_login import save_cookies

    try:
        if context is not None:
            save_cookies(context, cfg)
    except Exception:
        pass
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    _dispose_batch_browser(browser)
    return None, None, None


def _start_batch_browser(pw, cfg: dict, headless: bool):
    """启动 Chromium、恢复 cookie 或交互登录，并打开函数列表。返回 (browser, context, page)。"""
    from deployer.deploy_login import (
        ensure_logged_in_via_agent_or_manual,
        navigate_to_function_list,
        load_cookies,
        save_cookies,
    )

    browser = pw.chromium.launch(**_batch_playwright_launch_kw(headless))
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")

    has_session = load_cookies(context, cfg)
    if has_session:
        navigate_to_function_list(page, cfg)
        if login_path in page.url:
            print("  [批量] Session 已过期，重新登录...")
            has_session = False
        else:
            try:
                page.wait_for_selector(':text("新建APL函数"), :text("新建")', timeout=20000)
            except Exception:
                print("  [批量] 未检测到函数列表，Session 可能失效，重新登录...")
                has_session = False
    if not has_session:
        if not ensure_logged_in_via_agent_or_manual(page, cfg):
            _dispose_batch_browser(browser)
            raise RuntimeError("登录失败或超时，请重试。")
        save_cookies(context, cfg)
        navigate_to_function_list(page, cfg)
    return browser, context, page


def _ensure_batch_browser_page(pw, cfg: dict, headless: bool, browser, context, page):
    """每条任务前调用：浏览器被关则整实例重启；仅标签被关则新开 tab 并回函数列表。"""
    from deployer.deploy_login import navigate_to_function_list

    try:
        if browser is not None and browser.is_connected():
            if page is not None and not page.is_closed():
                return browser, context, page
            print("  [批量] 检测到标签页被关闭，新开标签页并进入函数列表…")
            page = context.new_page()
            navigate_to_function_list(page, cfg)
            return browser, context, page
    except Exception:
        pass

    print("\n  [批量] 浏览器不可用（可能已手动关闭窗口），正在重启 Chromium 并登录…")
    _dispose_batch_browser(browser)
    return _start_batch_browser(pw, cfg, headless)


def _execute_batch_records_loop(
    cfg: dict,
    pending: list,
    pw,
    headless: bool,
    no_refresh: bool,
    batch_round: int,
    browser,
    context,
    page,
    fx_proj: str,
    field_snapshot_cache: dict[tuple[str, str], list],
):
    """在同一 Playwright 进程中逐条执行 pending；每条记录结束后都会销毁浏览器态再进入下一条。返回 (results, browser, context, page)。"""
    from generator.generate import generate
    from deployer.deploy import _deploy_in_page, load_func_meta
    from deployer.deploy_login import dismiss_stale_apl_modals, navigate_to_function_list
    from feishu_record import (
        mark_bitable_record,
        STATUS_RUNNING, STATUS_OK, STATUS_FAIL,
        FIELD_DESC, FIELD_OBJECT,
    )

    if browser is None or context is None or page is None:
        browser, context, page = _start_batch_browser(pw, cfg, headless)

    results: list[dict] = []
    for i, record in enumerate(pending, 1):
        record_started = time.perf_counter()
        browser, context, page = _ensure_batch_browser_page(
            pw, cfg, headless, browser, context, page
        )
        dismiss_stale_apl_modals(page)
        navigate_to_function_list(page, cfg)

        record_id = record["record_id"]
        desc = record[FIELD_DESC]
        obj_label = record[FIELD_OBJECT]
        func_type_hint = record.get("函数类型", "")
        trigger_hint = (record.get("trigger_type") or "").strip()
        project_hint = (record.get("项目") or record.get("project") or "").strip()
        object_resolve_project = (project_hint or fx_proj).strip()
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
                object_resolve_project=object_resolve_project,
            )
            req_data = yaml.safe_load(req_content)
            sync_function_type_from_trigger_type(req_data)
            infer_function_type_into_req_if_missing(req_data)
            func_type = req_data.get("function_type", "")
            requires_binding_object = _function_requires_binding_object(func_type)

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".yml", dir=TOOLS_DIR,
                prefix="batch_req_", delete=False, encoding="utf-8"
            ) as f:
                f.write(req_content)
                tmp_path = f.name

            print(f"  [批量] 生成代码中...")
            # 与 pipeline --step all 一致：默认 force_refresh=True 从平台拉字段；--no-refresh 时仅用缓存
            fetch_started = time.perf_counter()
            try:
                fields_map = _load_fields_map_for_req(
                    req_data,
                    cfg,
                    force_refresh=not no_refresh,
                    page=page,
                    field_snapshot_cache=field_snapshot_cache,
                ) or {}
            except Exception as e:
                if requires_binding_object:
                    raise RuntimeError(f"字段抓取失败，已终止本条批量任务: {e}") from e
                print(f"  [批量] 字段抓取跳过: {e}")
                fields_map = {}
            print(f"  [耗时] 字段抓取: {time.perf_counter() - fetch_started:.1f}s")
            main_object_api = (req_data.get("object_api") or "").strip()
            if requires_binding_object and (not main_object_api or main_object_api not in fields_map):
                raise RuntimeError(
                    f"主对象字段未获取成功：{req_data.get('object_label') or '(未命名对象)'}"
                    f" ({main_object_api or '无 API'})。已停止生成，避免误部署。"
                )
            gen_started = time.perf_counter()
            apl_file = str(
                generate(req_data, cfg, fields_map=fields_map, req_file_path=tmp_path)
            )
            print(f"  [耗时] 生成代码: {time.perf_counter() - gen_started:.1f}s")
            func_name = Path(apl_file).stem

            # ── 部署（复用已有浏览器，回到函数列表即可）──
            namespace = resolve_namespace(req_data)
            object_label = req_data.get("object_label", "")
            raw_req = req_data.get("requirement", "") or ""
            description_text = raw_req.strip().splitlines()[0][:100] if raw_req.strip() else ""

            print(f"  [批量] 部署中: {func_name}")
            ok = False
            deploy_started = time.perf_counter()
            try:
                ok = _deploy_in_page(
                    page, apl_file, func_name, cfg,
                    namespace=namespace, object_label=object_label,
                    description=description_text, req=req_data,
                    fields_map_snapshot=fields_map,
                    ensure_login=False,
                )
            except Exception as de:
                err_detail = f"{type(de).__name__}: {de}\n{traceback.format_exc()}"
                err_fb = err_detail[:FEISHU_FEEDBACK_MAX]
                try:
                    mark_bitable_record(
                        cfg, record_id, STATUS_FAIL, error=err_fb,
                        risk_level="高", manual_action="查看执行反馈并按报错人工修正后重试",
                    )
                except Exception:
                    pass
                print(f"  ❌ 部署异常:\n{err_detail}")
                results.append({
                    "record_id": record_id, "desc": desc[:40],
                    "success": False, "func_name": func_name, "api_name": "",
                    "error": err_detail, "batch_round": batch_round,
                })
                continue
            print(f"  [耗时] 浏览器部署: {time.perf_counter() - deploy_started:.1f}s")

            meta = load_func_meta(apl_file)
            func_api_name = meta.get("func_api_name", "")

            if ok:
                fb = f"已生成并部署。系统API: {func_api_name or '见纷享'}。"
                risk_level = "低"
                manual_action = ""
                warning_notes: list[str] = []
                try:
                    from deployer.post_deploy import summarize_post_deploy
                    diag = summarize_post_deploy(apl_file, fields_map, req_data)
                    risk_level = diag.get("risk_level") or "低"
                    manual_action = diag.get("manual_action") or ""
                    warning_notes.extend(diag.get("warnings") or [])
                    cr = diag.get("credibility")
                    if cr:
                        print(f"  [批量] {cr['summary']}")
                except Exception as ce:
                    print(f"  [批量] 可信度校验跳过: {ce}")
                for note in warning_notes:
                    print(f"  [批量] ⚠ {note}")
                if warning_notes:
                    fb += " | " + " | ".join(warning_notes)
                if (
                    req_data.get("function_type") in ("范围规则", "关联对象范围规则")
                    and risk_level == "高"
                    and manual_action
                    and "OR 能力" in manual_action
                ):
                    fb += " | 请确认租户是否已开通 QueryTemplate.OR 能力；未开通时建议改为多分支 AND。"
                mark_bitable_record(
                    cfg, record_id, STATUS_OK,
                    func_name=func_name, api_name=func_api_name, feedback=fb[:FEISHU_FEEDBACK_MAX],
                    risk_level=risk_level, manual_action=manual_action,
                )
                print(f"  ✅ 成功: {func_name} ({func_api_name})")
                results.append({
                    "record_id": record_id, "desc": desc[:40],
                    "success": True, "func_name": func_name, "api_name": func_api_name,
                    "batch_round": batch_round,
                })
                print(f"  [耗时] 单条总计: {time.perf_counter() - record_started:.1f}s")
            else:
                err_fb = (
                    "部署未正常完成新建/保存。请根据执行反馈与平台当前页面状态人工检查后重试。"
                )[:FEISHU_FEEDBACK_MAX]
                mark_bitable_record(
                    cfg, record_id, STATUS_FAIL, error=err_fb,
                    risk_level="高", manual_action="查看执行反馈并按报错人工修正后重试",
                )
                print(f"  ❌ 失败: {err_fb}")
                results.append({
                    "record_id": record_id, "desc": desc[:40],
                    "success": False, "func_name": func_name, "api_name": "",
                    "error": err_fb, "batch_round": batch_round,
                })
                print(f"  [耗时] 单条总计: {time.perf_counter() - record_started:.1f}s")

        except Exception as e:
            err_detail = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            err_fb = err_detail[:FEISHU_FEEDBACK_MAX]
            try:
                mark_bitable_record(
                    cfg, record_id, STATUS_FAIL, error=err_fb,
                    risk_level="高", manual_action="查看执行反馈并按报错人工修正后重试",
                )
            except Exception:
                pass
            print(f"  ❌ 异常:\n{err_detail}")
            results.append({
                "record_id": record_id, "desc": desc[:40],
                "success": False, "func_name": "", "api_name": "",
                "error": err_detail, "batch_round": batch_round,
            })
            print(f"  [耗时] 单条总计: {time.perf_counter() - record_started:.1f}s")
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)
            try:
                dismiss_stale_apl_modals(page)
            except Exception:
                pass
            browser, context, page = _reset_batch_browser_state(browser, context, cfg)
    return results, browser, context, page

def run_batch_inprocess(
    cfg: dict,
    dry_run: bool = False,
    regenerate: bool = False,
    headless: bool = False,
    no_refresh: bool = False,
    batch_round: int = 1,
    project_filter: str = "",
) -> list[dict]:
    """单轮批量（供 dry-run 或独立调用）：自带 Playwright 生命周期，跑完即关浏览器。"""
    from playwright.sync_api import sync_playwright
    from feishu_record import (
        list_bitable_pending_records,
        clear_bitable_for_regenerate,
        FIELD_DESC, FIELD_OBJECT,
    )
    from deployer.deploy_login import save_cookies

    if regenerate:
        cleared = clear_bitable_for_regenerate(cfg)
        print(f"[批量] 重新生成模式：已清空 {cleared} 条记录的函数名/状态，即将重新执行")
        if cleared == 0:
            print("[批量] 没有可重新生成的记录（描述为空的行不参与）")
            return []

    pending = list_bitable_pending_records(cfg)
    pending = _filter_pending_by_project(pending, project_filter)
    if not pending:
        if project_filter:
            print(f"[批量] 项目「{project_filter}」下没有待执行的记录")
        else:
            print("[批量] 没有待执行的记录")
        print("  提示：需「描述」已填且「系统API名」为空；状态为待执行/空，或❌失败且系统API名仍为空（可自动重试）")
        print("  若想重做：清空该行的系统API名，或将状态改回待执行；或 batch_runner.py --regenerate")
        if project_filter:
            print("  另外请确认该行「项目」列已明确填写且与本次项目过滤一致。")
        return []

    print(f"[批量] 找到 {len(pending)} 条待执行记录" + (f"（第 {batch_round} 轮）" if batch_round > 1 else ""))
    fx_proj = ((cfg.get("fxiaoke") or {}).get("project_name") or "").strip()

    if dry_run:
        results = []
        for i, record in enumerate(pending, 1):
            desc = record[FIELD_DESC]
            obj_label = record[FIELD_OBJECT]
            ph = (record.get("项目") or record.get("project") or "").strip()
            resolve_p = ph or fx_proj
            req_content = _build_req_yml(
                desc, obj_label,
                function_type_hint=record.get("函数类型", ""),
                trigger_type_hint=(record.get("trigger_type") or "").strip(),
                project_hint=ph,
                object_resolve_project=resolve_p,
            )
            print(f"\n[批量] [dry-run] 第 {i}/{len(pending)} 条:\n{req_content}")
            results.append({"record_id": record["record_id"], "dry_run": True})
        return results

    with sync_playwright() as pw:
        browser, context, page = None, None, None
        field_snapshot_cache: dict[tuple[str, str], list] = {}
        try:
            results, browser, context, page = _execute_batch_records_loop(
                cfg, pending, pw, headless, no_refresh, batch_round,
                browser, context, page, fx_proj, field_snapshot_cache,
            )
        finally:
            try:
                save_cookies(context, cfg)
            except Exception:
                pass
            _dispose_batch_browser(browser)
    return results


def run_batch(
    cfg: dict,
    dry_run: bool = False,
    regenerate: bool = False,
    headless: bool = False,
    no_refresh: bool = False,
    retry_failed: bool = True,
    project_filter: str = "",
) -> list[dict]:
    """多轮重试共用一个浏览器会话，避免每轮结束就关窗口。"""
    from playwright.sync_api import sync_playwright
    from feishu_record import list_bitable_pending_records, clear_bitable_for_regenerate
    from deployer.deploy_login import save_cookies

    all_results: list[dict] = []
    max_pass = 1 + (MAX_RETRY_EXTRA_PASSES if retry_failed and not dry_run else 0)

    if dry_run:
        return run_batch_inprocess(
            cfg, dry_run=True, regenerate=regenerate, headless=headless,
            no_refresh=no_refresh, batch_round=1, project_filter=project_filter,
        )

    fx_proj = ((cfg.get("fxiaoke") or {}).get("project_name") or "").strip()
    browser = context = page = None
    retry_ids: set[str] | None = None

    with sync_playwright() as pw:
        try:
            for pass_i in range(1, max_pass + 1):
                field_snapshot_cache: dict[tuple[str, str], list] = {}
                if pass_i == 1 and regenerate:
                    cleared = clear_bitable_for_regenerate(cfg)
                    print(f"[批量] 重新生成模式：已清空 {cleared} 条记录的函数名/状态，即将重新执行")
                    if cleared == 0:
                        print("[批量] 没有可重新生成的记录（描述为空的行不参与）")
                        break

                pending_all = list_bitable_pending_records(cfg)
                pending_all = _filter_pending_by_project(pending_all, project_filter)
                if pass_i == 1 or retry_ids is None:
                    pending = pending_all
                else:
                    pending = [r for r in pending_all if r["record_id"] in retry_ids]
                if pass_i > 1:
                    if not pending:
                        print("[批量] 无待重试记录，结束重试。")
                        break
                    print(f"\n[批量] ========== 自动重试 第 {pass_i}/{max_pass} 轮（当前待执行 {len(pending)} 条）==========\n")
                elif not pending:
                    if project_filter:
                        print(f"[批量] 项目「{project_filter}」下没有待执行的记录")
                    else:
                        print("[批量] 没有待执行的记录")
                    print("  提示：需「描述」已填且「系统API名」为空；状态为待执行/空，或❌失败且系统API名仍为空（可自动重试）")
                    print("  若想重做：清空该行的系统API名，或将状态改回待执行；或 batch_runner.py --regenerate")
                    if project_filter:
                        print("  另外请确认该行「项目」列已明确填写且与本次项目过滤一致。")
                    break
                else:
                    print(f"[批量] 找到 {len(pending)} 条待执行记录" + (f"（第 {pass_i} 轮）" if pass_i > 1 else ""))

                if not pending:
                    continue

                batch, browser, context, page = _execute_batch_records_loop(
                    cfg, pending, pw, headless, no_refresh, pass_i,
                    browser, context, page, fx_proj, field_snapshot_cache,
                )
                all_results.extend(batch)
                retry_ids = {
                    r["record_id"]
                    for r in batch
                    if not r.get("success") and not r.get("dry_run")
                }

                if not retry_failed:
                    break
                had_fail = bool(retry_ids)
                if not had_fail:
                    print("[批量] 本轮无失败，不再重试。")
                    break
                if pass_i >= max_pass:
                    print(
                        f"[批量] 已达最大轮次（{max_pass}），仍有失败请查看终端「失败完整报错」或飞书「执行反馈」。"
                    )
                    break
        finally:
            try:
                save_cookies(context, cfg)
            except Exception:
                pass
            _dispose_batch_browser(browser)

    return all_results


def print_summary(results: list[dict]) -> str:
    """打印汇总；返回简短文本供飞书通知（含失败首行摘要）。"""
    if not results:
        msg = "没有待执行的记录。\n\n提示：在多维表格「描述」列填写需求，并保持「系统API名」为空，再发送「批量生成」。"
        print(msg)
        return msg

    lines = [f"批量执行完成，共 {len(results)} 条人次（含重试轮次）：\n"]
    ok = [r for r in results if r.get("success")]
    fail = [r for r in results if not r.get("success") and not r.get("dry_run")]

    for r in results:
        if r.get("dry_run"):
            lines.append(f"  📋 [dry-run] {r['record_id']}")
        elif r.get("success"):
            br = r.get("batch_round")
            tag = f" [R{br}]" if br and br > 1 else ""
            lines.append(f"  ✅{tag} {r['func_name'] or r['desc']} → {r['api_name'] or '(API名待确认)'}")
        else:
            br = r.get("batch_round")
            tag = f" [R{br}]" if br else ""
            d = (r.get("desc") or "")[:30]
            ell = "…" if len(r.get("desc") or "") > 30 else ""
            lines.append(f"  ❌{tag} {r['record_id']} {d}{ell} → 失败")

    lines.append(f"\n成功 {len(ok)} / 失败 {len(fail)} / 共 {len(results)} 条人次")

    if fail:
        lines.append("\n失败摘要（完整栈在下方终端 + 飞书「执行反馈」列）：")
        for r in fail:
            first = (r.get("error") or "（见飞书执行反馈）").strip().split("\n")[0]
            if len(first) > 200:
                first = first[:200] + "…"
            br = r.get("batch_round")
            tag = f"R{br} " if br else ""
            lines.append(f"  • {tag}{r['record_id']}: {first}")

    summary = "\n".join(lines)
    print(summary)

    for r in fail:
        err = (r.get("error") or "").strip()
        if err:
            print("\n" + "=" * 60)
            print(f"[失败完整报错] record_id={r['record_id']} batch_round={r.get('batch_round', '-')}")
            print("=" * 60)
            print(err)
            print("=" * 60)

    if fail and not any(r.get("error") for r in fail):
        print("\n[提示] 部分失败行未带回本地 error 文本，请打开飞书表查看「执行反馈」列。")

    return summary


def main():
    parser = argparse.ArgumentParser(description="批量 APL 函数生成器")
    parser.add_argument("--dry-run", action="store_true", help="仅预览待执行记录，不实际执行")
    parser.add_argument("--regenerate", action="store_true",
                        help="重新生成：先清空所有有描述行的函数名/状态，再批量执行")
    parser.add_argument("--headless", action="store_true",
                        help="无头模式（默认有界面，与 pipeline 一致；纷享在无头下易失败）")
    parser.add_argument("--headed", action="store_true",
                        help="兼容旧版：强制有界面（现为默认行为，一般无需加）")
    parser.add_argument("--no-refresh", dest="no_refresh", action="store_true",
                        help="字段不强制重拉，仅用本地缓存（与 pipeline 一致；默认每条都会向平台拉取/更新缓存）")
    parser.add_argument(
        "--no-retry",
        dest="retry_failed",
        action="store_false",
        help="仅执行一轮；默认会在本轮出现失败时自动多轮重试（最多共 4 轮，识别飞书中仍可重试的行）",
    )
    parser.set_defaults(retry_failed=True)
    parser.add_argument("--config", default=None, help="config 文件路径")
    parser.add_argument("--bitable-app-token", dest="bitable_app_token", default=None,
                        help="覆盖 config 中的多维表格 app_token")
    parser.add_argument("--bitable-table-id", dest="bitable_table_id", default=None,
                        help="覆盖 config 中的多维表格 table_id")
    parser.add_argument("--no-notify", dest="no_notify", action="store_true",
                        help="跳过批量完成后的飞书通知，仅本地执行（调试回归用）")
    parser.add_argument("--runtime-precheck", dest="runtime_precheck", action="store_true",
                        help="部署前调用系统 runtime/debug 预检编译错误（默认关闭，不影响原流程）")
    parser.add_argument("--web-create-api", dest="web_create_api", action="store_true",
                        help="新建函数时优先走 Web Session create 接口（默认关闭，失败回退浏览器）")
    parser.add_argument("--project", default=None,
                        help="仅执行指定项目的记录（按飞书表「项目」列精确匹配）")
    args = parser.parse_args()
    _acquire_batch_lock()

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
                f"[批量] 已清理临时文件 {cleanup.get('cleaned_temp', 0)} 个，"
                f"归档修复报告 {cleanup.get('archived_reports', 0)} 个"
            )
    except Exception:
        pass
    if args.bitable_app_token or args.bitable_table_id:
        cfg.setdefault("feishu", {})
        if args.bitable_app_token:
            cfg["feishu"]["bitable_app_token"] = args.bitable_app_token.strip()
        if args.bitable_table_id:
            cfg["feishu"]["bitable_table_id"] = args.bitable_table_id.strip()
    headless = bool(args.headless)
    if getattr(args, "headed", False):
        headless = False
    results = run_batch(
        cfg,
        dry_run=args.dry_run,
        regenerate=args.regenerate,
        headless=headless,
        no_refresh=getattr(args, "no_refresh", False),
        retry_failed=getattr(args, "retry_failed", True),
        project_filter=(args.project or "").strip(),
    )
    summary = print_summary(results)

    # 批量完成后直接推送飞书通知，不依赖 agent 回复
    if not args.dry_run and not getattr(args, "no_notify", False):
        try:
            from feishu_record import send_feishu_notify
            send_feishu_notify(summary, cfg)
        except Exception:
            pass


if __name__ == "__main__":
    main()
