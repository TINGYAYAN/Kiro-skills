"""
代理登录：调用 GetAdminAgentLoginToken 获取 token，通过 SSOLogin 直接登录

前置条件：已有有效 session（cookies），通常来自管理员账号的首次登录。
配置：config.fxiaoke.agent_login_employee_id = "1001"  # 要代理登录的员工 ID
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

import requests

_TOOLS = Path(__file__).parent.parent


def _cookies_to_jar(cookies: list) -> tuple[dict, str]:
    """将 Playwright cookies 转为 {name: value} 和 fs_token。"""
    jar = {}
    fs_token = ""
    for c in cookies:
        name = c.get("name", "")
        value = str(c.get("value", ""))
        if name:
            jar[name] = value
            if name == "fs_token":
                fs_token = value
    return jar, fs_token


def get_agent_login_url(
    cookies: list,
    employee_id: str,
    base_url: str,
) -> Optional[str]:
    """
    调用 GetAdminAgentLoginToken 获取代理登录 token，返回 SSOLogin URL。

    Args:
        cookies: Playwright 格式的 cookies（context.cookies() 或 session 文件中的 cookies）
        employee_id: 要代理登录的员工 ID，如 "1001"
        base_url: 纷享基址，如 https://www.fxiaoke.com

    Returns:
        SSOLogin URL，如 https://www.fxiaoke.com/FHH/EM0HXUL/SSOLogin?token=xxx
        失败返回 None
    """
    base_url = base_url.rstrip("/")
    jar, fs_token = _cookies_to_jar(cookies)
    trace_id = f"E-E.pipeline.{int(time.time() * 1000)}"

    url = f"{base_url}/FHH/EM1HNCRM/API/v1/object/personnelrest/service/GetAdminAgentLoginToken"
    params = {"_fs_token": fs_token or "trace", "traceId": trace_id}
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/json; charset=UTF-8",
        "origin": base_url,
        "referer": f"{base_url}/XV/UI/manage",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    try:
        resp = requests.post(
            url,
            params=params,
            headers=headers,
            cookies=jar,
            json={"employeeId": employee_id},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        status = data.get("Result", {}).get("StatusCode", data.get("StatusCode", -1))
        if status != 0:
            return None

        val = data.get("Value", data.get("data", data))
        if isinstance(val, dict):
            login_url = val.get("loginUrl")
            if login_url:
                return login_url
            token = val.get("token") or val.get("agentLoginToken") or val.get("loginToken")
            if token:
                return f"{base_url}/FHH/EM0HXUL/SSO/Login?token={token}"
        elif isinstance(val, str):
            return val if val.startswith("http") else f"{base_url}/FHH/EM0HXUL/SSO/Login?token={val}"
    except Exception:
        pass
    return None


def get_session_cookies(cfg: dict) -> Optional[list]:
    """从 session 文件读取 cookies（用于调用 GetAdminAgentLoginToken），无文件或解析失败返回 None。"""
    from deployer.deploy_login import get_session_path
    path = get_session_path(cfg)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cookies = data.get("cookies", data) if isinstance(data, dict) else data
        return cookies if cookies else None
    except Exception:
        return None


def login_via_agent(page, cfg: dict, cookies: Optional[list] = None) -> bool:
    """
    调用 GetAdminAgentLoginToken 获取带 token 的 URL，跳转后完成登录。不使用 Playwright 自动填表。

    需要 config.fxiaoke.agent_login_employee_id 配置员工 ID。
    cookies 来自 session 文件或调用方传入（需为管理员账号的有效 session）。
    """
    employee_id = (cfg.get("fxiaoke") or {}).get("agent_login_employee_id", "").strip()
    if not employee_id:
        return False

    if not cookies:
        cookies = get_session_cookies(cfg)
    if not cookies:
        return False

    base_url = cfg["fxiaoke"].get("base_url", "https://www.fxiaoke.com").rstrip("/")
    sso_url = get_agent_login_url(cookies, employee_id, base_url)
    if not sso_url:
        return False

    print(f"[部署器] 代理登录: 获取 token 成功，跳转 SSOLogin (employeeId={employee_id})")
    page.goto(sso_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")
    still_on_login = login_path in page.url
    if not still_on_login:
        try:
            still_on_login = bool(page.locator(':text("扫码登录"), :text("账号登录"), :text("动态验证码登录")').first)
        except Exception:
            pass

    return not still_on_login
