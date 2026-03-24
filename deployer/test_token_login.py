"""
测试 token 登录 URL：
1) 直接用给定 URL 跳转，检查是否登录成功
2) 调用 GetAdminAgentLoginToken 生成新 URL，确认格式一致

用法：
  python -m deployer.test_token_login
  python -m deployer.test_token_login --token-url "https://www.fxiaoke.com/FHH/EM0HXUL/SSO/Login?token=xxx"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_TOOLS = Path(__file__).parent.parent
sys.path.insert(0, str(_TOOLS))

from utils import load_config


def test_token_url_navigate(token_url: str, cfg: dict) -> bool:
    """用 Playwright 打开 token URL，检查是否成功离开登录页。"""
    from playwright.sync_api import sync_playwright
    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        try:
            print(f"\n[1] 打开 token URL...")
            page.goto(token_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            cur = page.url
            print(f"    当前 URL: {cur}")
            on_login = login_path in cur
            if not on_login:
                try:
                    on_login = page.locator(':text("扫码登录"), :text("账号登录")').first.is_visible(timeout=1500)
                except Exception:
                    pass
            if on_login:
                print("    结果: 仍在登录页（token 可能已过期）")
                return False
            print("    结果: 已离开登录页，登录成功")
            return True
        finally:
            browser.close()


def test_api_generate_url(cfg: dict) :
    """调用 GetAdminAgentLoginToken 生成新 URL。"""
    from deployer.agent_login import get_agent_login_url, get_session_cookies

    cookies = get_session_cookies(cfg)
    if not cookies:
        print("\n[2] 无 session 文件，无法调用接口生成 URL（需先手动登录一次）")
        return None
    employee_id = (cfg.get("fxiaoke") or {}).get("agent_login_employee_id", "1001").strip()
    base_url = cfg["fxiaoke"].get("base_url", "https://www.fxiaoke.com").rstrip("/")
    url = get_agent_login_url(cookies, employee_id, base_url)
    if url:
        print(f"\n[2] 接口生成的 URL:\n    {url}")
        return url
    print("\n[2] 接口调用失败（cookies 可能已过期）")
    return None


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--token-url", default="https://www.fxiaoke.com/FHH/EM0HXUL/SSO/Login?token=88c55c8b52bb47f4a67411b570987cac")
    parser.add_argument("--skip-navigate", action="store_true", help="跳过 URL 跳转测试")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)

    if not args.skip_navigate:
        ok = test_token_url_navigate(args.token_url, cfg)
        if not ok:
            print("\n提示: token 可能已过期（一次性使用），请用接口生成新 URL 测试")
    else:
        print("\n[1] 已跳过 URL 跳转测试")

    url = test_api_generate_url(cfg)
    if url:
        print("\n格式一致，下次登录会调用接口生成上述形式的 URL")
    else:
        print("\n请先手动登录一次，保存 session 后即可用接口生成 URL")


if __name__ == "__main__":
    main()
