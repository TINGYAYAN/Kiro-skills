from __future__ import annotations

import argparse
import cgi
import csv
import io
import json
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import NAMESPACE_TO_CODE_PREFIX, infer_short_code_summary, load_config, resolve_namespace

WEB_DIR = ROOT / "web_console"
TEMPLATE_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
RUNTIME_DIR = WEB_DIR / "runtime"
HISTORY_FILE = RUNTIME_DIR / "history.json"

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _load_history() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(items: list[dict[str, Any]]) -> None:
    HISTORY_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_history(item: dict[str, Any]) -> None:
    items = _load_history()
    items.insert(0, item)
    _save_history(items[:200])


def _update_history(task_id: str, **patch: Any) -> None:
    items = _load_history()
    changed = False
    for item in items:
        if item.get("id") == task_id:
            item.update(patch)
            changed = True
            break
    if changed:
        _save_history(items)


def _detect_projects(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    fx = cfg.get("fxiaoke") or {}
    names: set[str] = set()
    current = (fx.get("project_name") or "").strip()
    if current:
        names.add(current)
    for name in (fx.get("sharedev_projects") or {}).keys():
        if str(name).strip():
            names.add(str(name).strip())
    sharedev_dir = ROOT / "sharedev_pull"
    if sharedev_dir.exists():
        for child in sharedev_dir.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                names.add(child.name.strip())

    result: list[dict[str, Any]] = []
    for name in sorted(n for n in names if n):
        session_path = ROOT / "deployer" / f"session_{name}.json"
        req_path = ROOT / "sharedev_pull" / name / "req.yml"
        proj_cfg = ((fx.get("sharedev_projects") or {}).get(name) or {})
        result.append(
            {
                "name": name,
                "is_current": name == current,
                "has_session": session_path.exists(),
                "has_req": req_path.exists(),
                "has_certificate": bool((proj_cfg.get("certificate") or "").strip()),
                "session_path": str(session_path) if session_path.exists() else "",
                "req_path": str(req_path) if req_path.exists() else "",
            }
        )
    return result


def _session_summary() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted((ROOT / "deployer").glob("session_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cookies = data.get("cookies") or []
        except Exception:
            cookies = []
        key_cookies = {}
        for name in ("fs_token", "JSESSIONID", "FSAuthX", "FSAuthXC"):
            cookie = next((c for c in cookies if c.get("name") == name), None)
            if not cookie:
                continue
            expires = cookie.get("expires")
            if expires in (-1, None):
                exp_text = "session"
            else:
                exp_text = datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M:%S")
            key_cookies[name] = exp_text
        out.append(
            {
                "file": str(path),
                "project": path.stem.replace("session_", "", 1),
                "cookies": key_cookies,
            }
        )
    return out


def _cert_summary(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    fx = cfg.get("fxiaoke") or {}
    out: list[dict[str, Any]] = []
    for name, proj in sorted((fx.get("sharedev_projects") or {}).items()):
        cert = (proj.get("certificate") or "").strip()
        out.append(
            {
                "project": name,
                "domain": (proj.get("domain") or "").strip(),
                "certificate_preview": f"{cert[:8]}...{cert[-8:]}" if len(cert) > 16 else cert,
                "has_certificate": bool(cert),
            }
        )
    return out


def _settings_summary(cfg: dict[str, Any]) -> dict[str, Any]:
    fx = cfg.get("fxiaoke") or {}
    deployer = cfg.get("deployer") or {}
    current = (fx.get("project_name") or "").strip()
    project_cfg = ((fx.get("sharedev_projects") or {}).get(current) or {})
    return {
        "project_name": current,
        "bootstrap_token_url": (fx.get("bootstrap_token_url") or "").strip(),
        "agent_login_employee_id": (fx.get("agent_login_employee_id") or "").strip(),
        "username": (fx.get("username") or "").strip(),
        "domain": (project_cfg.get("domain") or fx.get("base_url") or "").strip(),
        "runtime_debug_precheck": bool(deployer.get("runtime_debug_precheck")),
        "web_create_api": bool(deployer.get("web_create_api")),
        "project_domains": {
            str(name).strip(): str((proj or {}).get("domain") or "").strip()
            for name, proj in ((fx.get("sharedev_projects") or {}).items())
            if str(name).strip()
        },
    }


def _runtime_cfg_for_project(cfg: dict[str, Any], project: str) -> dict[str, Any]:
    runtime_cfg = json.loads(json.dumps(cfg, ensure_ascii=False))
    runtime_cfg.setdefault("fxiaoke", {})["project_name"] = project
    return runtime_cfg


def _format_cookie_expiry(expires: Any) -> str:
    if expires in (-1, None, "", 0):
        return "会话有效"
    try:
        return datetime.fromtimestamp(float(expires)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"


def _session_status_items(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from deployer.deploy_login import get_session_path

    items: list[dict[str, Any]] = []
    for item in _detect_projects(cfg):
        project = item["name"]
        runtime_cfg = _runtime_cfg_for_project(cfg, project)
        session_path = get_session_path(runtime_cfg)
        cookies: list[dict[str, Any]] = []
        if session_path.exists():
            try:
                data = json.loads(session_path.read_text(encoding="utf-8"))
                cookies = data.get("cookies", data) if isinstance(data, dict) else data
                if not isinstance(cookies, list):
                    cookies = []
            except Exception:
                cookies = []
        target_names = {"fs_token", "FSAuthX", "FSAuthXC", "JSESSIONID"}
        cookie_map = {str(c.get("name") or ""): c for c in cookies if str(c.get("name") or "") in target_names}
        hard_expiries = []
        for name in ("fs_token", "FSAuthX", "FSAuthXC"):
            cookie = cookie_map.get(name)
            if not cookie:
                continue
            expires = cookie.get("expires")
            if expires not in (-1, None, "", 0):
                try:
                    hard_expiries.append(float(expires))
                except Exception:
                    pass
        expires_at = _format_cookie_expiry(min(hard_expiries) if hard_expiries else None)
        logged_in = bool(cookie_map.get("JSESSIONID") and (cookie_map.get("fs_token") or cookie_map.get("FSAuthX")))
        items.append(
            {
                "project": project,
                "logged_in": logged_in,
                "expires_at": expires_at,
                "can_refresh": logged_in,
                "session_path": str(session_path),
            }
        )
    return items


def _load_project_objects(project_name: str) -> list[dict[str, str]]:
    project = (project_name or "").strip()
    if not project:
        return []
    path = ROOT / "sharedev_pull" / project / "objects.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items: list[dict[str, str]] = []
    for item in raw if isinstance(raw, list) else []:
        api_name = str(item.get("api_name") or "").strip()
        label = str(item.get("display_name") or item.get("label") or "").strip()
        if not api_name:
            continue
        items.append(
            {
                "api_name": api_name,
                "label": label or api_name,
                "display": f"{label or api_name} ({api_name})",
            }
        )
    items.sort(key=lambda x: (x["label"], x["api_name"]))
    return items


def _load_project_functions(project_name: str) -> list[dict[str, Any]]:
    project = (project_name or "").strip()
    if not project:
        return []
    path = ROOT / "sharedev_pull" / project / "functions.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def _function_type_label(name_space: str) -> str:
    mapping = {
        "flow": "流程函数",
        "button": "按钮",
        "ui_event": "UI函数",
        "scheduler_task": "计划任务",
        "scope_rule": "范围规则",
        "apl_controller": "自定义控制器",
        "controller": "自定义控制器",
    }
    return mapping.get((name_space or "").strip(), (name_space or "").strip() or "函数")


def _format_ms_timestamp(value: Any) -> str:
    if value in (None, "", 0):
        return ""
    try:
        ts = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def _function_desc(function: dict[str, Any]) -> str:
    return (
        str(function.get("remark") or "").strip()
        or _extract_doc_value(str(function.get("body") or ""), "description")
        or str(function.get("function_name") or function.get("code_name") or "").strip()
    )


def _extract_doc_value(body: str, key: str) -> str:
    m = re.search(rf"@{re.escape(key)}\s+(.+)", body or "", flags=re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _find_function_detail(project: str, api_name: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    api = (api_name or "").strip()
    if not api:
        return None
    local = next((f for f in _load_project_functions(project) if str(f.get("api_name") or "").strip() == api), None)
    if local:
        return dict(local)
    try:
        from fetcher.sharedev_client import load_sharedev_config, ShareDevClient

        domain, cert = load_sharedev_config(ROOT, project or None)
        client = ShareDevClient(domain, cert)
        items = client.get_func_by_api_names([api])
        return dict(items[0]) if items else None
    except Exception:
        return None


def _function_doc_rows(project: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in _load_project_functions(project):
        rows.append(
            {
                "项目": project,
                "需求描述": _function_desc(item),
                "函数名": str(item.get("function_name") or item.get("code_name") or "").strip(),
                "系统API": str(item.get("api_name") or "").strip(),
                "函数类型": _function_type_label(str(item.get("name_space") or item.get("namespace") or "")),
                "执行时间": _format_ms_timestamp(item.get("update_time") or item.get("create_time")),
            }
        )
    rows.sort(key=lambda x: (x["函数类型"], x["函数名"], x["系统API"]))
    return rows


def _renew_session_for_project(cfg: dict[str, Any], project: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright
    from deployer.agent_login import get_session_cookies, get_agent_login_url
    from deployer.deploy_login import save_cookies

    runtime_cfg = _runtime_cfg_for_project(cfg, project)
    cookies = get_session_cookies(runtime_cfg)
    if not cookies:
        raise RuntimeError("当前项目还没有可用登录态，无法续签。请先手动登录一次。")
    employee_id = ((runtime_cfg.get("fxiaoke") or {}).get("agent_login_employee_id") or "").strip()
    if not employee_id:
        raise RuntimeError("未配置代理员工 ID，无法获取代理登录地址。")
    base_url = ((runtime_cfg.get("fxiaoke") or {}).get("base_url") or "https://www.fxiaoke.com").rstrip("/")
    sso_url = get_agent_login_url(cookies, employee_id, base_url)
    if not sso_url:
        raise RuntimeError("获取代理登录地址失败，当前 session 可能已失效。")

    login_path = (runtime_cfg.get("fxiaoke") or {}).get("login_path", "/XV/UI/login")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        try:
            page.goto(sso_url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(8):
                time.sleep(2)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                cur = page.url
                on_login = (login_path in cur or "proj/page/login" in cur or "/page/login" in cur)
                if not on_login:
                    break
            cur = page.url
            if "proj/page/login" in cur or (login_path in cur and "login" in cur.lower()):
                raise RuntimeError("代理地址已生成，但未完成自动登录，可能需要重新获取 session。")
            save_cookies(context, runtime_cfg)
        finally:
            browser.close()
    item = next((x for x in _session_status_items(runtime_cfg) if x["project"] == project), None)
    return item or {"project": project, "logged_in": False, "expires_at": "未知", "can_refresh": False}


def _csv_response(handler: BaseHTTPRequestHandler, rows: list[dict[str, str]], filename: str) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["项目", "需求描述", "函数名", "系统API", "函数类型", "执行时间"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    body = output.getvalue().encode("utf-8-sig")
    handler.send_response(200)
    handler.send_header("Content-Type", "text/csv; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "functions.csv"
    handler.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
    handler.end_headers()
    handler.wfile.write(body)


def _normalize_function_detail(project: str, function: dict[str, Any]) -> dict[str, Any]:
    body = str(function.get("body") or "")
    function_name = str(function.get("function_name") or function.get("code_name") or "").strip()
    api_name = str(function.get("api_name") or "").strip()
    name_space = str(function.get("name_space") or function.get("namespace") or "").strip()
    binding_api = str(function.get("binding_object_api_name") or "").strip()
    binding_label = (
        str(function.get("binding_object_label") or "").strip()
        or _extract_doc_value(body, "bindingObjectLabel")
    )
    description = (
        str(function.get("remark") or "").strip()
        or _extract_doc_value(body, "description")
        or function_name
    )
    updated_at = _format_ms_timestamp(function.get("update_time") or function.get("create_time"))
    return {
        "project": project,
        "function_name": function_name,
        "api_name": api_name,
        "function_type": _function_type_label(name_space),
        "binding_object_label": binding_label,
        "binding_object_api_name": binding_api,
        "description": description,
        "updated_at": updated_at,
        "name_space": name_space,
        "body": body,
    }


def _runtime_debug_for_function(project: str, api_name: str, cfg: dict[str, Any]) -> dict[str, Any]:
    detail = _find_function_detail(project, api_name, cfg)
    if not detail:
        raise RuntimeError("未找到对应函数，无法获取运行日志。")
    normalized = _normalize_function_detail(project, detail)
    from fetcher.sharedev_client import ShareDevRuntimeClient

    runtime_cfg = _runtime_cfg_for_project(cfg, project)
    client = ShareDevRuntimeClient.from_config(project_root=ROOT, project_name=project, cfg=runtime_cfg)
    function_payload = client.build_function_payload(
        api_name=normalized["api_name"],
        body=normalized["body"],
        binding_object_api_name=normalized["binding_object_api_name"],
        function_name=normalized["function_name"],
        binding_object_label=normalized["binding_object_label"],
        name_space=normalized["name_space"],
        existing_function=detail,
    )
    result = client.runtime_debug(
        api_name=normalized["api_name"],
        binding_object_api_name=normalized["binding_object_api_name"],
        function=function_payload,
    )
    value = result.get("Value") or {}
    return {
        "project": project,
        "function_name": normalized["function_name"],
        "api_name": normalized["api_name"],
        "success": bool(value.get("success")),
        "log_info": str(value.get("logInfo") or "").strip(),
        "error_info": str(value.get("errorInfo") or value.get("error") or "").strip(),
    }


def _read_task_artifact(task: dict[str, Any]) -> dict[str, Any] | None:
    req = task.get("req_snapshot") or {}
    project = str(req.get("project") or "").strip()
    log_path = Path(str(task.get("log_path") or ""))
    if not log_path.exists():
        return None
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    apl_path: Path | None = None
    match = re.search(r"\[生成器\]\s+已输出:\s+(.+?\.apl)", text)
    if match:
        apl_path = Path(match.group(1).strip())
    elif task.get("func_name"):
        candidate = ROOT.parent / f"{str(task.get('func_name') or '').strip()}.apl"
        if candidate.exists():
            apl_path = candidate
    if not apl_path or not apl_path.exists():
        return None
    return {
        "project": project,
        "function_name": apl_path.stem,
        "api_name": str(task.get("api_name") or "").strip(),
        "function_type": str(req.get("function_type") or "").strip() or "函数",
        "binding_object_label": str(req.get("object_label") or "").strip(),
        "binding_object_api_name": str(req.get("object_api") or "").strip(),
        "description": str(req.get("requirement") or "").strip(),
        "updated_at": str(task.get("finished_at") or task.get("started_at") or ""),
        "body": apl_path.read_text(encoding="utf-8", errors="ignore"),
    }


def _build_single_req(payload: dict[str, Any]) -> dict[str, Any]:
    req = {
        "requirement": (payload.get("requirement") or "").strip(),
        "object_api": (payload.get("object_api") or "").strip(),
        "object_label": (payload.get("object_label") or "").strip(),
        "function_type": (payload.get("function_type") or "流程函数").strip(),
        "project": (payload.get("project") or "").strip(),
    }
    code_name = (payload.get("code_name") or "").strip()
    if code_name:
        req["code_name"] = code_name
    elif req["requirement"]:
        req["code_name"] = _infer_web_code_name(req["requirement"], req["object_label"], req["function_type"])
    return req


def _extract_quoted_fields(text: str) -> list[str]:
    return [m.strip() for m in re.findall(r"[“\"]([^”\"]+)[”\"]", text or "") if m.strip()]


def _infer_web_code_name(requirement: str, object_label: str, function_type: str) -> str:
    text = (requirement or "").strip()
    req = {"function_type": function_type}
    prefix = NAMESPACE_TO_CODE_PREFIX.get(resolve_namespace(req), "【流程】")
    fields = _extract_quoted_fields(text)
    if "查询" in text and "更新" in text:
        src = fields[0] if fields else ""
        dst = fields[-1] if len(fields) > 1 else ""
        if src and dst and src != dst:
            return f"{prefix}按{src}更新{dst}"
    if "同步" in text and fields:
        return f"{prefix}同步{fields[-1]}"
    summary = infer_short_code_summary(text, object_label)
    return f"{prefix}{summary}"


def _build_runtime_config(base_cfg: dict[str, Any], *, project: str = "", web_create_api: bool = False) -> Path:
    runtime_cfg = json.loads(json.dumps(base_cfg, ensure_ascii=False))
    fx = runtime_cfg.setdefault("fxiaoke", {})
    deployer = runtime_cfg.setdefault("deployer", {})
    if project:
        fx["project_name"] = project
    if web_create_api:
        deployer["web_create_api"] = True
    config_path = RUNTIME_DIR / f"cfg_{uuid.uuid4().hex[:10]}.yml"
    _write_yaml(config_path, runtime_cfg)
    return config_path


def _parse_datetime_like(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _filter_tasks(items: list[dict[str, Any]], query: dict[str, str]) -> list[dict[str, Any]]:
    project = (query.get("project") or [""])[0].strip()
    status = (query.get("status") or [""])[0].strip()
    kind = (query.get("kind") or [""])[0].strip()
    deploy_result = (query.get("deploy_result") or [""])[0].strip()
    api_name = (query.get("api_name") or [""])[0].strip().lower()
    date_from = _parse_datetime_like((query.get("date_from") or [""])[0])
    date_to = _parse_datetime_like((query.get("date_to") or [""])[0])

    def include(task: dict[str, Any]) -> bool:
        title = str(task.get("title") or "")
        if project and project not in title and project != (task.get("req_snapshot") or {}).get("project", ""):
            return False
        if status and task.get("status") != status:
            return False
        if kind and task.get("kind") != kind:
            return False
        if deploy_result:
            deploy_message = str(task.get("deploy_message") or "")
            if deploy_result == "success" and "成功" not in deploy_message:
                return False
            if deploy_result == "failed" and "失败" not in deploy_message:
                return False
        if api_name and api_name not in str(task.get("api_name") or "").lower():
            return False
        started = _parse_datetime_like(str(task.get("started_at") or ""))
        if date_from and (not started or started < date_from):
            return False
        if date_to and (not started or started > date_to.replace(hour=23, minute=59, second=59)):
            return False
        return True

    return [item for item in items if include(item)]


def _infer_function_type_from_text(text: str) -> str:
    desc = (text or "").strip()
    if any(kw in desc for kw in ["范围规则", "可选范围", "介绍人", "范围"]):
        return "范围规则"
    if any(kw in desc for kw in ["UI事件", "UI函数", "页面加载", "页面初始化", "默认值"]):
        return "UI函数"
    if any(kw in desc for kw in ["按钮", "点击", "按钮函数"]):
        return "按钮"
    if any(kw in desc for kw in ["计划任务", "定时", "每天", "每周", "cron"]):
        return "计划任务"
    if any(kw in desc for kw in ["控制器", "接口", "controller"]):
        return "自定义控制器"
    return "流程函数"


def _guess_object_from_text(project_name: str, text: str) -> dict[str, str]:
    desc = (text or "").strip()
    objects = _load_project_objects(project_name)
    if not desc or not objects:
        return {}
    scored: list[tuple[int, dict[str, str]]] = []
    for item in objects:
        score = 0
        label = item["label"]
        api_name = item["api_name"]
        if label and label in desc:
            score += len(label) * 10
        if api_name and api_name in desc:
            score += len(api_name) * 8
        compact = label.replace("对象", "") if label else label
        if compact and compact != label and compact in desc:
            score += len(compact) * 6
        if score > 0:
            scored.append((score, item))
    if not scored:
        return {}
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _build_chat_draft(payload: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    project = (payload.get("project") or (cfg.get("fxiaoke") or {}).get("project_name") or "").strip()
    requirement = (payload.get("message") or "").strip()
    explicit_type = (payload.get("function_type") or "").strip()
    function_type = explicit_type or _infer_function_type_from_text(requirement)
    guessed_object = _guess_object_from_text(project, requirement)
    req = {
        "project": project,
        "requirement": requirement,
        "function_type": function_type,
        "object_api": guessed_object.get("api_name", ""),
        "object_label": guessed_object.get("label", ""),
    }
    if req["object_api"] and req["object_label"]:
        status = "ready"
        assistant = (
            f"已生成 req 草稿。绑定对象识别为「{req['object_label']}」"
            f"（{req['object_api']}），函数类型为「{function_type}」。"
        )
    else:
        status = "need_object"
        assistant = (
            "我先把需求收到了，但还没从当前项目对象中唯一识别出绑定对象。"
            " 你可以在下面的对象下拉里补选，再直接执行。"
        )
    return {
        "status": status,
        "assistant": assistant,
        "req": req,
        "objects": _load_project_objects(project),
    }


def _task_status_from_log(text: str) -> dict[str, Any]:
    compile_message = ""
    deploy_message = ""
    api_name = ""
    func_name = ""
    if m := re.search(r"\[pipeline\]\s+(本地编译[^\n]+)", text):
        compile_message = m.group(1).strip()
    if m := re.search(r"✅ 部署成功：([^\n]+)", text):
        func_name = m.group(1).strip()
        deploy_message = "部署成功"
    elif "部署失败" in text:
        deploy_message = "部署失败"
    if m := re.search(r"API名[：:]\s*([A-Za-z0-9_]+__c)", text):
        api_name = m.group(1).strip()
    elif m := re.search(r"函数 API 名.*?[：:]\s*([A-Za-z0-9_]+__c)", text):
        api_name = m.group(1).strip()
    return {
        "compile_message": compile_message,
        "deploy_message": deploy_message,
        "api_name": api_name,
        "func_name": func_name,
    }


class TaskManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            current = list(self._tasks.values())
        history = _load_history()
        existing = {item["id"] for item in current}
        for item in history:
            if item.get("id") not in existing:
                current.append(item)
        current.sort(key=lambda item: item.get("started_at", ""), reverse=True)
        return current

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            if task_id in self._tasks:
                return dict(self._tasks[task_id])
        for item in _load_history():
            if item.get("id") == task_id:
                return item
        return None

    def _set(self, task_id: str, **patch: Any) -> None:
        with self._lock:
            task = self._tasks.setdefault(task_id, {})
            task.update(patch)
        _update_history(task_id, **patch)

    def launch(self, *, kind: str, title: str, cmd: list[str], req_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
        task_id = uuid.uuid4().hex[:12]
        log_path = RUNTIME_DIR / f"{task_id}.log"
        task = {
            "id": task_id,
            "kind": kind,
            "title": title,
            "cmd": cmd,
            "status": "running",
            "started_at": _now_text(),
            "finished_at": "",
            "log_path": str(log_path),
            "req_snapshot": req_snapshot or {},
            "compile_message": "",
            "deploy_message": "",
            "api_name": "",
            "func_name": "",
            "exit_code": None,
        }
        with self._lock:
            self._tasks[task_id] = task
        _append_history(task)

        thread = threading.Thread(target=self._run_task, args=(task_id, cmd, log_path), daemon=True)
        thread.start()
        return task

    def rerun(self, task_id: str) -> dict[str, Any]:
        task = self.get(task_id)
        if not task:
            raise KeyError("task not found")
        if task.get("status") == "running":
            raise RuntimeError("任务仍在执行中，不能重复发起。")
        cmd = task.get("cmd") or []
        if not isinstance(cmd, list) or not cmd:
            raise RuntimeError("原任务缺少可复用执行命令，无法重新执行。")
        return self.launch(
            kind=str(task.get("kind") or "single"),
            title=str(task.get("title") or "重新执行"),
            cmd=[str(x) for x in cmd],
            req_snapshot=dict(task.get("req_snapshot") or {}),
        )

    def _run_task(self, task_id: str, cmd: list[str], log_path: Path) -> None:
        with log_path.open("w", encoding="utf-8") as fh:
            fh.write(f"[task] started_at={_now_text()}\n")
            fh.write(f"[task] cmd={' '.join(cmd)}\n\n")
            fh.flush()
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                fh.write(line)
                fh.flush()
            proc.wait()
            fh.write(f"\n[task] finished_at={_now_text()} exit_code={proc.returncode}\n")
            fh.flush()

        text = log_path.read_text(encoding="utf-8", errors="ignore")
        parsed = _task_status_from_log(text)
        self._set(
            task_id,
            status="success" if proc.returncode == 0 else "failed",
            finished_at=_now_text(),
            exit_code=proc.returncode,
            **parsed,
        )


TASKS = TaskManager()


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _binary_response(handler: BaseHTTPRequestHandler, body: bytes, status: int = 200, content_type: str = "application/octet-stream") -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "APLWebConsole/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        cfg = load_config(None)

        if path == "/":
            template = env.get_template("index.html")
            html = template.render()
            return _text_response(self, html, content_type="text/html; charset=utf-8")

        if path.startswith("/static/"):
            file_path = STATIC_DIR / path.replace("/static/", "", 1)
            if not file_path.exists():
                return _text_response(self, "Not Found", status=404)
            ctype = "application/octet-stream"
            if file_path.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            elif file_path.suffix == ".js":
                ctype = "application/javascript; charset=utf-8"
            elif file_path.suffix == ".png":
                ctype = "image/png"
            elif file_path.suffix in {".jpg", ".jpeg"}:
                ctype = "image/jpeg"
            elif file_path.suffix == ".svg":
                ctype = "image/svg+xml; charset=utf-8"
            if file_path.suffix in {".css", ".js", ".svg"}:
                return _text_response(self, file_path.read_text(encoding="utf-8"), content_type=ctype)
            return _binary_response(self, file_path.read_bytes(), content_type=ctype)

        if path == "/api/projects":
            return _json_response(self, {"items": _detect_projects(cfg)})

        if path == "/api/project-objects":
            project = (parse_qs(parsed.query).get("project") or [""])[0].strip()
            return _json_response(
                self,
                {
                    "project": project,
                    "items": _load_project_objects(project),
                },
            )

        if path == "/api/dashboard":
            return _json_response(
                self,
                {
                    "projects": _detect_projects(cfg),
                    "settings": _settings_summary(cfg),
                    "tasks": TASKS.list()[:20],
                },
            )

        if path == "/api/session-status":
            return _json_response(self, {"items": _session_status_items(cfg)})

        if path == "/api/functions/export":
            project = (parse_qs(parsed.query).get("project") or [""])[0].strip() or ((cfg.get("fxiaoke") or {}).get("project_name") or "").strip()
            rows = _function_doc_rows(project)
            return _csv_response(self, rows, f"函数需求文档_{project or '项目'}_{datetime.now().strftime('%Y%m%d')}.csv")

        if path == "/api/functions/detail":
            query = parse_qs(parsed.query)
            project = (query.get("project") or [""])[0].strip() or ((cfg.get("fxiaoke") or {}).get("project_name") or "").strip()
            api_name = (query.get("api_name") or [""])[0].strip()
            detail = _find_function_detail(project, api_name, cfg)
            if not detail:
                return _json_response(self, {"error": "function not found"}, status=404)
            return _json_response(self, {"item": _normalize_function_detail(project, detail)})

        if path == "/api/chat/draft":
            return _json_response(self, {"error": "method not allowed"}, status=405)

        if path == "/api/tasks":
            filtered = _filter_tasks(TASKS.list(), parse_qs(parsed.query))
            return _json_response(self, {"items": filtered})

        if path == "/api/templates/batch":
            kind = (parse_qs(parsed.query).get("kind") or ["example"])[0].strip() or "example"
            file_path = ROOT / ("bitable_template_blank.csv" if kind == "blank" else "bitable_template_example.csv")
            if not file_path.exists():
                return _text_response(self, "Not Found", status=404)
            body = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{file_path.name}"')
            self.end_headers()
            self.wfile.write(body)
            return

        if path.startswith("/api/tasks/") and path.endswith("/log"):
            task_id = path.split("/")[3]
            task = TASKS.get(task_id)
            if not task:
                return _json_response(self, {"error": "task not found"}, status=404)
            log_path = Path(task["log_path"])
            content = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.exists() else ""
            return _text_response(self, content)

        if path.startswith("/api/tasks/") and path.endswith("/artifact"):
            task_id = path.split("/")[3]
            task = TASKS.get(task_id)
            if not task:
                return _json_response(self, {"error": "task not found"}, status=404)
            artifact = _read_task_artifact(task)
            if not artifact:
                return _json_response(self, {"error": "artifact not found"}, status=404)
            return _json_response(self, {"item": artifact})

        if path.startswith("/api/tasks/"):
            task_id = path.split("/")[3]
            task = TASKS.get(task_id)
            if not task:
                return _json_response(self, {"error": "task not found"}, status=404)
            return _json_response(self, task)

        return _text_response(self, "Not Found", status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        cfg = load_config(None)

        if path == "/api/run/single":
            payload = self._read_json()
            req = _build_single_req(payload)
            project = (req.get("project") or (cfg.get("fxiaoke") or {}).get("project_name") or "").strip()
            if req["requirement"] and (not req["object_api"] or not req["object_label"]):
                guessed_object = _guess_object_from_text(project, req["requirement"])
                if guessed_object:
                    req["object_api"] = req["object_api"] or guessed_object.get("api_name", "")
                    req["object_label"] = req["object_label"] or guessed_object.get("label", "")
            if not req["requirement"] or not req["object_api"] or not req["object_label"]:
                return _json_response(
                    self,
                    {
                        "error": "需求正文和绑定对象不能为空；如果没手动选对象，请在需求里明确写出对象名",
                        "req": req,
                    },
                    status=400,
                )
            req_file = RUNTIME_DIR / f"req_{uuid.uuid4().hex[:10]}.yml"
            _write_yaml(req_file, req)
            runtime_cfg_path = _build_runtime_config(
                cfg,
                project=project,
                web_create_api=bool(payload.get("web_create_api")),
            )
            cmd = [
                sys.executable,
                "pipeline.py",
                "--config",
                str(runtime_cfg_path),
                "--req",
                str(req_file),
                "--step",
                "deploy",
                "--runtime-precheck",
                "--no-feishu-log",
            ]
            if payload.get("web_create_api"):
                cmd.append("--web-create-api")
            if payload.get("no_notify", True):
                cmd.append("--no-notify")
            if project:
                cmd.extend(["--project", project])
            task = TASKS.launch(
                kind="single",
                title=f"单条生成 · {project or '未指定项目'}",
                cmd=cmd,
                req_snapshot=req,
            )
            return _json_response(self, task, status=201)

        if path == "/api/run/batch":
            payload = self._read_json()
            project = (payload.get("project") or "").strip()
            runtime_cfg_path = _build_runtime_config(
                cfg,
                project=project,
                web_create_api=bool(payload.get("web_create_api")),
            )
            cmd = [sys.executable, "batch_runner.py", "--config", str(runtime_cfg_path), "--runtime-precheck"]
            if payload.get("web_create_api"):
                cmd.append("--web-create-api")
            if payload.get("dry_run"):
                cmd.append("--dry-run")
            if payload.get("regenerate"):
                cmd.append("--regenerate")
            if payload.get("no_notify", True):
                cmd.append("--no-notify")
            if project:
                cmd.extend(["--project", project])
            task = TASKS.launch(
                kind="batch",
                title=f"批量生成 · {project or '当前项目'}",
                cmd=cmd,
                req_snapshot={"project": project, "dry_run": bool(payload.get("dry_run")), "regenerate": bool(payload.get("regenerate"))},
            )
            return _json_response(self, task, status=201)

        if path == "/api/run/batch-upload":
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
            upload = form["file"] if "file" in form else None
            if upload is None or not getattr(upload, "file", None):
                return _json_response(self, {"error": "请上传 CSV 模板文件"}, status=400)
            filename = Path(getattr(upload, "filename", "") or "uploaded_batch.csv").name
            saved = RUNTIME_DIR / f"upload_{uuid.uuid4().hex[:8]}_{filename}"
            saved.write_bytes(upload.file.read())
            project = str(form.getfirst("project", "") or "").strip()
            no_notify = str(form.getfirst("no_notify", "true")).lower() in {"1", "true", "on", "yes"}
            web_create_api = str(form.getfirst("web_create_api", "true")).lower() in {"1", "true", "on", "yes"}
            runtime_cfg_path = _build_runtime_config(cfg, project=project, web_create_api=web_create_api)
            cmd = [
                sys.executable,
                str(ROOT / "web_console" / "run_uploaded_batch.py"),
                "--config",
                str(runtime_cfg_path),
                "--csv",
                str(saved),
            ]
            if project:
                cmd.extend(["--project", project])
            if no_notify:
                cmd.append("--no-notify")
            if web_create_api:
                cmd.append("--web-create-api")
            task = TASKS.launch(
                kind="batch_upload",
                title=f"批量生成（模板上传） · {project or '全部项目'}",
                cmd=cmd,
                req_snapshot={"project": project, "upload": saved.name},
            )
            return _json_response(self, task, status=201)

        if path == "/api/session-refresh":
            payload = self._read_json()
            project = (payload.get("project") or "").strip()
            if not project:
                return _json_response(self, {"error": "project required"}, status=400)
            item = _renew_session_for_project(cfg, project)
            return _json_response(self, {"item": item}, status=200)

        if path == "/api/functions/runtime-log":
            payload = self._read_json()
            project = (payload.get("project") or "").strip() or ((cfg.get("fxiaoke") or {}).get("project_name") or "").strip()
            api_name = (payload.get("api_name") or "").strip()
            if not api_name:
                return _json_response(self, {"error": "api_name required"}, status=400)
            try:
                result = _runtime_debug_for_function(project, api_name, cfg)
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, status=400)
            return _json_response(self, result, status=200)

        if path.startswith("/api/tasks/") and path.endswith("/rerun"):
            task_id = path.split("/")[3]
            task = TASKS.get(task_id)
            if not task:
                return _json_response(self, {"error": "task not found"}, status=404)
            if task.get("status") != "failed":
                return _json_response(self, {"error": "only failed tasks can rerun"}, status=400)
            try:
                new_task = TASKS.rerun(task_id)
            except Exception as exc:
                return _json_response(self, {"error": str(exc)}, status=400)
            return _json_response(self, new_task, status=201)

        if path == "/api/settings":
            payload = self._read_json()
            config_path = ROOT / "config.local.yml"
            data = _read_yaml(config_path)
            fx = data.setdefault("fxiaoke", {})
            deployer = data.setdefault("deployer", {})
            sharedev = fx.setdefault("sharedev_projects", {})

            if "project_name" in payload:
                fx["project_name"] = (payload.get("project_name") or "").strip()
            if "bootstrap_token_url" in payload:
                fx["bootstrap_token_url"] = (payload.get("bootstrap_token_url") or "").strip()
            if "agent_login_employee_id" in payload:
                fx["agent_login_employee_id"] = (payload.get("agent_login_employee_id") or "").strip()
            if "username" in payload:
                fx["username"] = (payload.get("username") or "").strip()
            if "password" in payload:
                password = (payload.get("password") or "").strip()
                if password:
                    fx["password"] = password
            if "runtime_debug_precheck" in payload:
                deployer["runtime_debug_precheck"] = bool(payload.get("runtime_debug_precheck"))
            if "web_create_api" in payload:
                deployer["web_create_api"] = bool(payload.get("web_create_api"))
            selected_project = (payload.get("project_name") or fx.get("project_name") or "").strip()
            if selected_project:
                proj_cfg = sharedev.setdefault(selected_project, {})
                if "domain" in payload:
                    proj_cfg["domain"] = (payload.get("domain") or "").strip()

            cert_payload = payload.get("certificate")
            if isinstance(cert_payload, dict):
                proj_name = (cert_payload.get("project") or "").strip()
                if proj_name:
                    proj_cfg = sharedev.setdefault(proj_name, {})
                    if "certificate" in cert_payload:
                        proj_cfg["certificate"] = (cert_payload.get("certificate") or "").strip()

            _write_yaml(config_path, data)
            return _json_response(self, {"ok": True})

        return _text_response(self, "Not Found", status=404)


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"[web] 控制台已启动: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="APL 自动化 Web 控制台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run(host=args.host, port=args.port)
