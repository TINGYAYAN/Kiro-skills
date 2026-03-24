"""
通过 token URL 登录，保存 cookies 到 session 文件。用于首次/切换环境时快速建立 session。

用法：
  python -m deployer.bootstrap_token_login "https://www.fxiaoke.com/FHH/EM0HXUL/SSO/Login?token=xxx"
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_TOOLS = Path(__file__).parent.parent
sys.path.insert(0, str(_TOOLS))

from utils import load_config
from deployer.deploy_login import save_cookies, get_session_path


def bootstrap(token_url: str, config_path = None) -> bool:
    """打开 token URL，等待登录成功，保存 cookies。"""
    from playwright.sync_api import sync_playwright

    cfg = load_config(config_path)
    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        try:
            print(f"[bootstrap] 打开 token URL...")
            page.goto(token_url, wait_until="domcontentloaded", timeout=30000)
            for _ in range(8):
                time.sleep(4)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                cur = page.url
                on_login = (login_path in cur or "proj/page/login" in cur or "/page/login" in cur)
                if on_login:
                    try:
                        if page.locator(':text("扫码登录"), :text("账号登录"), :text("动态验证码登录")').first.is_visible(timeout=2000):
                            print("[bootstrap] 等待跳转...")
                            continue
                    except Exception:
                        pass
                if not on_login:
                    break
                if _ < 7:
                    print("[bootstrap] 等待跳转...")
            cur = page.url
            if "proj/page/login" in cur or (login_path in cur and "login" in cur.lower()):
                print("[bootstrap] 仍在登录页，token 可能已过期或无效")
                return False
            print("[bootstrap] 登录成功，保存 cookies...")
            save_cookies(context, cfg)
            print(f"[bootstrap] 已保存到 {get_session_path(cfg)}")
            return True
        finally:
            browser.close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("token_url", help="SSO token 登录 URL")
    p.add_argument("--config", default=None)
    args = p.parse_args()
    ok = bootstrap(args.token_url, args.config)
    sys.exit(0 if ok else 1)
