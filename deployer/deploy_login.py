"""
登录与 Session 管理

- 登录纷享销客
- Session 按项目分文件存放，文件内带项目注释
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import keyring

_TOOLS = Path(__file__).parent.parent
DEPLOYER_DIR = Path(__file__).parent
SCREENSHOTS_DIR = DEPLOYER_DIR / "screenshots"
SERVICE_NAME = "fx_pipeline"


def _session_path(cfg: dict) -> Path:
    """Session 文件路径。按项目分文件：session_硅基流动.json；未配置项目则用 session_cookies.json。"""
    project = (cfg.get("fxiaoke") or {}).get("project_name", "").strip()
    if project:
        safe = re.sub(r'[/\\:*?"<>|]', "_", project)
        return DEPLOYER_DIR / f"session_{safe}.json"
    return DEPLOYER_DIR / "session_cookies.json"


def get_session_path(cfg: dict) -> Path:
    """供 fetcher 等模块获取 session 路径。"""
    return _session_path(cfg)


def get_password(cfg: dict) -> str:
    """优先读取 config 中的 password，否则从 keyring 获取。"""
    pw = cfg["fxiaoke"].get("password", "")
    if pw:
        return pw
    stored = keyring.get_password(SERVICE_NAME, cfg["fxiaoke"]["username"])
    if stored:
        return stored
    import getpass
    pw = getpass.getpass(f"请输入纷享销客密码 ({cfg['fxiaoke']['username']}): ")
    keyring.set_password(SERVICE_NAME, cfg["fxiaoke"]["username"], pw)
    return pw


def save_cookies(context, cfg: dict):
    """保存 Session，文件内带项目注释。"""
    path = _session_path(cfg)
    project = (cfg.get("fxiaoke") or {}).get("project_name", "").strip() or "(未配置项目)"
    data = {
        "_project": project,
        "_comment": f"Session 所属项目：{project}（来自 config.fxiaoke.project_name）",
        "cookies": context.cookies(),
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [部署器] Session 已保存: {path}（项目：{project}）")


def load_cookies(context, cfg: dict) -> bool:
    """加载 Session。兼容旧格式（纯 cookies 数组）。"""
    path = _session_path(cfg)
    if not path.exists():
        return False
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, list):
            cookies = data
        else:
            cookies = data.get("cookies", data)
        if cookies:
            context.add_cookies(cookies)
            project = data.get("_project", "") if isinstance(data, dict) else ""
            print(f"  [部署器] 已加载 Session（项目：{project or '未知'}）")
            return True
    except Exception:
        pass
    return False


def screenshot(page, name: str):
    """截取当前页面，若页面/浏览器已关闭则静默跳过。"""
    try:
        SCREENSHOTS_DIR.mkdir(exist_ok=True)
        path = SCREENSHOTS_DIR / f"{name}_{int(time.time())}.png"
        page.screenshot(path=str(path))
        print(f"  [截图] {path}")
    except Exception as e:
        err_name = type(e).__name__
        if "TargetClosed" in err_name or "closed" in str(e).lower():
            return
        raise


def _try_selector(page, selectors, timeout: int = 4000):
    from deployer import selectors as sel
    if isinstance(selectors, str):
        selectors = [selectors]
    for s in selectors:
        try:
            loc = page.locator(s).first
            loc.wait_for(timeout=timeout)
            return loc
        except Exception:
            continue
    return None


def _ocr_captcha_with_llm(page, img_locator, clip_rect: dict = None) -> str:
    """截取验证码图片区域，调用 LLM 视觉识别，返回验证码字符串。失败返回空字符串。"""
    import base64
    try:
        if img_locator is not None:
            img_bytes = img_locator.screenshot()
        elif clip_rect:
            img_bytes = page.screenshot(clip=clip_rect)
        else:
            img_bytes = page.screenshot()
    except Exception:
        try:
            img_bytes = page.screenshot()
        except Exception:
            return ""
    b64 = base64.b64encode(img_bytes).decode()
    try:
        import httpx
        from utils import load_config
        cfg = load_config(None)
        llm_cfg = cfg.get("llm", {})
        api_key = llm_cfg.get("api_key", "")
        base_url = llm_cfg.get("base_url", "https://api.openai.com/v1").rstrip("/")
        model = llm_cfg.get("model", "gpt-4o")
        prompt = (
            "图片中包含一个图形验证码（可能是扭曲的字母和数字组合）。"
            "请只输出验证码文字，不要解释，不要标点，不要空格。"
        )
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": 20,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                    ]
                }]
            },
            timeout=30
        )
        data = resp.json()
        if data.get("error"):
            raise ValueError(data.get("error") or data)
        if "choices" in data and data["choices"]:
            result = data["choices"][0].get("message", {}).get("content", "").strip()
        elif "content" in data and data["content"]:
            block = data["content"][0] if isinstance(data["content"], list) else data["content"]
            result = (block.get("text", "") if isinstance(block, dict) else str(block)).strip()
        else:
            result = ""
        return result.replace(" ", "").replace("\n", "")[:8] if result else ""
    except Exception as e:
        print(f"  [验证码OCR] LLM 调用失败: {e}")
        return ""


def _fill_and_click_login(page):
    """点击登录按钮（统一出口）。"""
    page.evaluate("""
        () => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                if (el.childElementCount === 0 && el.textContent.trim() === '登录'
                        && el.getBoundingClientRect().height > 0) {
                    el.click(); break;
                }
            }
        }
    """)


def _handle_graphic_captcha(page) -> bool:
    """检测并处理表单内的图形验证码（点登录前调用）。
    返回 True 表示检测到并处理（填完后需调用方重新点登录），False 表示无图形验证码。"""
    # 图形验证码的输入框 placeholder 包含「图形」
    captcha_input = None
    for ph in ['图形验证码', '图形码']:
        try:
            loc = page.locator(f'input[placeholder*="{ph}"]').first
            if loc.is_visible(timeout=1500):
                captcha_input = loc
                break
        except Exception:
            continue
    if not captcha_input:
        return False

    print("  [部署器] 检测到图形验证码，LLM 视觉识别中...")

    # 找验证码图片 bounding box，截取精确区域送 LLM
    clip_rect = None
    try:
        clip_rect = page.evaluate("""
            () => {
                const inputs = [...document.querySelectorAll('input')];
                const inp = inputs.find(i => (i.placeholder||'').includes('图形'));
                if (!inp) return null;
                let p = inp.parentElement;
                for (let i = 0; i < 6; i++) {
                    if (!p) break;
                    const img = p.querySelector('img');
                    if (img) {
                        const r = img.getBoundingClientRect();
                        if (r.height > 10) return {x: r.x, y: r.y, width: r.width, height: r.height};
                    }
                    p = p.parentElement;
                }
                return null;
            }
        """)
    except Exception:
        clip_rect = None

    # LLM OCR
    code = _ocr_captcha_with_llm(page, None, clip_rect=clip_rect)
    if code:
        print(f"  [部署器] 图形验证码识别结果: {code}")
        try:
            captcha_input.fill(code)
            time.sleep(0.3)
            return True
        except Exception as e:
            print(f"  [警告] 填写图形验证码失败: {e}")

    # OCR 失败 → 截图 + 终端输入
    shot_path = SCREENSHOTS_DIR / f"captcha_{int(time.time())}.png"
    try:
        page.screenshot(path=str(shot_path))
    except Exception:
        pass
    print(f"  ⚠️  图形验证码识别失败，截图: {shot_path}")
    print("  请查看截图并在此输入图形验证码后按回车：", end="", flush=True)
    manual = input().strip()
    if manual:
        try:
            captcha_input.fill(manual)
            time.sleep(0.3)
            _fill_and_click_login(page)
            print("  [部署器] 已提交验证码并点击登录")
            time.sleep(2)
        except Exception:
            pass
    return True  # 无论如何都返回 True，让调用方继续


def _handle_sms_code(page):
    """检测并处理点击登录后弹出的短信/动态验证码输入框（终端输入）。"""
    # 只匹配明确的短信验证码，排除图形验证码
    sms_selectors = [
        'input[placeholder*="动态验证码"]',
        'input[placeholder*="短信验证码"]',
        'input[placeholder*="手机验证码"]',
    ]
    code_input = None
    for sel_str in sms_selectors:
        try:
            loc = page.locator(sel_str).first
            if loc.is_visible(timeout=3000):
                code_input = loc
                break
        except Exception:
            continue
    if not code_input:
        return

    shot_path = SCREENSHOTS_DIR / f"sms_code_{int(time.time())}.png"
    try:
        page.screenshot(path=str(shot_path))
    except Exception:
        pass
    print("\n" + "=" * 55)
    print("  ⚠️  需要短信验证码！")
    print(f"  截图: {shot_path}")
    print("  请查看手机短信，在此输入验证码后按回车：", end="", flush=True)
    code = input().strip()
    if code:
        try:
            code_input.fill(code)
            time.sleep(0.3)
            _fill_and_click_login(page)
            print("  [部署器] 短信验证码已提交，等待跳转...")
            time.sleep(1)
        except Exception as e:
            print(f"  [警告] 提交短信验证码失败: {e}，请手动完成后按回车...")
            input()
    else:
        print("  请手动完成后按回车继续...")
        input()
    print("=" * 55)


def wait_for_manual_login(page, cfg: dict, timeout_sec: int = 300) -> bool:
    """
    打开登录页，等待用户手动完成登录，检测到离开登录页后返回 True。
    不使用 Playwright 自动填表，避免验证码、选择器不稳定等问题。
    """
    base_url = cfg["fxiaoke"]["base_url"].rstrip("/")
    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")
    login_url = base_url + login_path
    print(f"[部署器] 打开登录页: {login_url}")
    page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(2)
    print("\n" + "=" * 60)
    print("  请在浏览器中手动完成登录（账号/密码/验证码等）")
    print("  登录成功后本程序将自动继续，最长等待 {} 秒".format(timeout_sec))
    print("=" * 60 + "\n")
    import time as _time
    start = _time.time()
    while _time.time() - start < timeout_sec:
        try:
            if login_path not in page.url:
                try:
                    if not page.locator(':text("扫码登录"), :text("账号登录"), :text("动态验证码登录")').first.is_visible(timeout=500):
                        print("  [部署器] 检测到登录成功")
                        return True
                except Exception:
                    pass
                print("  [部署器] 检测到登录成功")
                return True
        except Exception:
            pass
        _time.sleep(2)
    return False


def ensure_logged_in_via_agent_or_manual(page, cfg: dict) -> bool:
    """
    优先代理登录（调用 GetAdminAgentLoginToken 获取 token URL），失败则等待用户手动登录。
    不使用 Playwright 自动填表。返回 True 表示已登录。
    """
    from deployer.agent_login import login_via_agent, get_session_cookies
    agent_id = (cfg.get("fxiaoke") or {}).get("agent_login_employee_id", "").strip()
    if agent_id:
        cookies = get_session_cookies(cfg)
        if cookies and login_via_agent(page, cfg, cookies):
            return True
    return wait_for_manual_login(page, cfg)


def login(page, cfg: dict):
    from deployer import selectors as sel
    base_url = cfg["fxiaoke"]["base_url"].rstrip("/")
    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")
    login_url = base_url + login_path
    print(f"[部署器] 打开登录页: {login_url}")
    page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)  # 首次加载需更长时间，避免输入框未就绪导致登录失败
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    username = cfg["fxiaoke"]["username"]
    password = get_password(cfg)

    # 切到「账号登录」Tab，最多尝试3种方式确保切换成功
    for _attempt in range(3):
        tab_loc = _try_selector(page, [sel.LOGIN_ACCOUNT_TAB] + getattr(sel, "LOGIN_ACCOUNT_TAB_ALT", []), timeout=5000)
        if tab_loc:
            try:
                tab_loc.click()
            except Exception:
                try:
                    tab_loc.evaluate("el => el.click()")
                except Exception:
                    pass
        # 等账号输入框出现（确认切换成功）
        try:
            page.wait_for_selector(
                'input[type="text"], input[type="tel"], input[placeholder*="账号"], input[placeholder*="手机"]',
                timeout=3000
            )
            break
        except Exception:
            time.sleep(0.5)

    username_loc = _try_selector(page, [sel.LOGIN_USERNAME] + getattr(sel, "LOGIN_USERNAME_ALT", []), timeout=10000)
    if not username_loc:
        screenshot(page, "login_page_debug")
        raise RuntimeError(
            "未找到登录输入框，已截图保存到 deployer/screenshots/。\n"
            "请用 PWDEBUG=1 python deployer/deploy.py --file xxx.apl --func-name xxx 打开 Inspector 查看页面结构，\n"
            "再更新 deployer/selectors.py 中的 LOGIN_USERNAME_ALT。详见 TROUBLESHOOTING.md「登录页选择器失效」。"
        )
    # 纷享登录页加载时输入框可能短暂 readonly，需先移除再填写
    try:
        username_loc.evaluate("el => { el.removeAttribute('readonly'); el.removeAttribute('disabled'); }")
    except Exception:
        pass
    username_loc.fill(username)

    pwd_loc = _try_selector(page, [sel.LOGIN_PASSWORD] + getattr(sel, "LOGIN_PASSWORD_ALT", []), timeout=5000)
    if not pwd_loc:
        screenshot(page, "login_page_debug")
        raise RuntimeError("未找到密码输入框，已截图。请更新 selectors.py 中的 LOGIN_PASSWORD_ALT。")
    try:
        pwd_loc.evaluate("el => { el.removeAttribute('readonly'); el.removeAttribute('disabled'); }")
    except Exception:
        pass
    pwd_loc.fill(password)
    time.sleep(0.5)

    page.evaluate("""
        const boxes = document.querySelectorAll('input[type="checkbox"]');
        const unchecked = Array.from(boxes).filter(cb => !cb.checked);
        if (unchecked.length > 0) unchecked[unchecked.length - 1].click();
    """)
    time.sleep(0.5)

    # 点登录前检查图形验证码（出现在表单内）
    _handle_graphic_captcha(page)

    screenshot(page, "02_agreement_checked")
    _fill_and_click_login(page)
    time.sleep(1.5)

    try:
        agree_btn = page.locator(':text("同意并登录")')
        agree_btn.wait_for(timeout=5000)
        agree_btn.click()
        print("  [部署器] 已点击「同意并登录」")
        time.sleep(1)
    except Exception:
        pass

    # 点登录后可能出现图形验证码（服务器端触发，最多重试 3 次）
    for _cap_retry in range(3):
        if not _handle_graphic_captcha(page):
            break
        print(f"  [部署器] 图形验证码处理完毕，重新点击登录（第 {_cap_retry + 1} 次）...")
        _fill_and_click_login(page)
        time.sleep(1.5)

    # 点登录后检查短信验证码
    _handle_sms_code(page)

    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")
    try:
        page.wait_for_url(lambda url: login_path not in url, timeout=60000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    # 验证是否真正离开了登录页（URL + 登录UI双重检查）
    still_on_login = login_path in page.url
    if not still_on_login:
        try:
            still_on_login = page.locator(
                ':text("扫码登录"), :text("账号登录"), :text("动态验证码登录")'
            ).first.is_visible(timeout=1500)
        except Exception:
            pass
    if still_on_login:
        # 首次登录常因页面未就绪失败，重试一次
        print("  [部署器] 登录未跳转，3 秒后重试...")
        time.sleep(3)
        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=20000)
        except Exception:
            pass
        time.sleep(2)
        for _retry in range(3):
            tab_loc = _try_selector(page, [sel.LOGIN_ACCOUNT_TAB] + getattr(sel, "LOGIN_ACCOUNT_TAB_ALT", []), timeout=3000)
            if tab_loc:
                try:
                    tab_loc.click()
                    time.sleep(0.5)
                except Exception:
                    pass
            username_loc = _try_selector(page, [sel.LOGIN_USERNAME] + getattr(sel, "LOGIN_USERNAME_ALT", []), timeout=5000)
            if username_loc:
                try:
                    username_loc.evaluate("el => { el.removeAttribute('readonly'); el.removeAttribute('disabled'); }")
                except Exception:
                    pass
                username_loc.fill(username)
            pwd_loc = _try_selector(page, [sel.LOGIN_PASSWORD] + getattr(sel, "LOGIN_PASSWORD_ALT", []), timeout=3000)
            if pwd_loc:
                try:
                    pwd_loc.evaluate("el => { el.removeAttribute('readonly'); el.removeAttribute('disabled'); }")
                except Exception:
                    pass
                pwd_loc.fill(password)
            _handle_graphic_captcha(page)
            _fill_and_click_login(page)
            time.sleep(1.5)
            try:
                agree_btn = page.locator(':text("同意并登录")')
                if agree_btn.is_visible(timeout=2000):
                    agree_btn.click()
                    time.sleep(0.5)
            except Exception:
                pass
            try:
                page.wait_for_url(lambda url: login_path not in url, timeout=15000)
            except Exception:
                pass
            still_on_login = login_path in page.url
            if not still_on_login:
                break
        if still_on_login:
            screenshot(page, "login_failed")
            raise RuntimeError(
                "登录失败：点击登录后页面未跳转。可能原因：验证码填写错误、账号密码错误或需要手动处理。"
            )
    screenshot(page, "01_login_success")
    print("[部署器] 登录成功")


def dismiss_stale_apl_modals(page) -> None:
    """关闭仍打开的 APL 弹层、Element 错误提示框、关闭确认，避免批量下一条被遮挡。"""
    for _ in range(12):
        acted = False
        try:
            msgbox = page.locator(
                ".el-message-box__wrapper, .fx-message-box__wrapper, [aria-label='错误提示']"
            ).first
            if msgbox.is_visible(timeout=350):
                for sel in (
                    ".el-message-box__btns .el-button--primary",
                    "button:has-text(\"确定\")",
                    ".fx-message-box__wrapper button.el-button--primary",
                    "button:has-text(\"我知道了\")",
                ):
                    try:
                        page.locator(sel).first.click(timeout=1200)
                        acted = True
                        time.sleep(0.4)
                        break
                    except Exception:
                        continue
                if not acted:
                    try:
                        msgbox.press("Enter")
                        time.sleep(0.3)
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            for hint in ("关闭后设置的函数", "确认要关闭"):
                box = page.locator(
                    ".el-message-box__wrapper, .fx-message-box__wrapper"
                ).filter(has_text=hint).first
                if box.is_visible(timeout=400):
                    for sel in (
                        'button:has-text("确定")',
                        ".el-message-box__btns .el-button--primary",
                        'span:has-text("确定")',
                        'button:has-text("确认")',
                    ):
                        try:
                            box.locator(sel).first.click(timeout=1500)
                            acted = True
                            time.sleep(0.5)
                            break
                        except Exception:
                            continue
                    if acted:
                        break
        except Exception:
            pass
        try:
            for hint in ("关闭后设置的函数", "确认要关闭"):
                pdlg = page.locator(
                    ".paas-func-dialog, .f-g-dialog.paas-func-dialog-height"
                ).filter(has_text=hint).first
                if pdlg.is_visible(timeout=400):
                    for sel in (
                        'button:has-text("确定")',
                        ".el-button--primary",
                        'span:has-text("确定")',
                    ):
                        try:
                            pdlg.locator(sel).first.click(force=True, timeout=2000)
                            acted = True
                            time.sleep(0.5)
                            break
                        except Exception:
                            continue
                    if acted:
                        break
        except Exception:
            pass
        try:
            dlg = page.locator(".paas-func-dialog, .f-g-dialog.paas-func-dialog-height").first
            if dlg.is_visible(timeout=400):
                try:
                    dlg.locator(':text-is("取消")').last.click(force=True, timeout=2000)
                    acted = True
                    time.sleep(0.45)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            page.keyboard.press("Escape")
            time.sleep(0.12)
        except Exception:
            pass
        if not acted:
            break


def navigate_to_function_list(page, cfg: dict):
    base_url = cfg["fxiaoke"]["base_url"].rstrip("/")
    func_path = cfg["fxiaoke"].get("function_path", "/XV/UI/manage#crmmanage/=/module-myfunction")
    url = base_url + func_path
    print(f"[部署器] 导航到函数管理页: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(5)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass


def get_frame(page):
    """等待函数列表核心元素出现（最多 20 秒），确保 SPA 渲染完成。
    若主页面未找到，尝试在 iframe 内查找（纷享部分租户将函数列表放在 iframe）。"""
    READY_SELECTORS = [
        ':text("新建APL函数")',
        ':text("新建自定义APL函数")',
        ':text("新建函数")',
        ':text("新建")',
        'input[placeholder*="搜索代码名称"]',
        'input[placeholder*="搜索"]',
        'input[placeholder*="Search"]',
    ]
    for sel in READY_SELECTORS:
        try:
            page.wait_for_selector(sel, timeout=20000)
            print("  [部署器] 函数列表已加载")
            return page
        except Exception:
            continue
    for frame in page.frames():
        if frame == page.main_frame:
            continue
        try:
            for sel in READY_SELECTORS[:2]:
                if frame.locator(sel).count() > 0:
                    print("  [部署器] 函数列表在 iframe 内，已定位")
                    return frame
        except Exception:
            continue
    print("  [警告] 等待函数列表内容超时，继续尝试...")
    return page
