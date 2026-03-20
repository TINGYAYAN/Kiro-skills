"""
字段 API 名抓取器

从纷享销客 APL 编辑器的「字段API对照表」标签页中自动抓取指定对象的所有字段，
缓存到本地 .fields_cache/ 目录，供代码生成器使用。

缓存按项目分目录（config.fxiaoke.project_name）：
  .fields_cache/硅基流动/tenant__c.yml
  .fields_cache/硅基流动/AccountObj.yml
未配置项目名时使用根目录 .fields_cache/*.yml（兼容旧结构）。

用法：
  # 抓取主对象字段（项目名从 config 读取）
  python -m fetcher.fetch_fields --object-api tenant__c --object-label 租户

  # 指定项目名
  python -m fetcher.fetch_fields --object-api tenant__c --object-label 租户 --project 硅基流动

  # 强制刷新缓存
  python -m fetcher.fetch_fields --object-api tenant__c --object-label 租户 --force
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config, infer_related_objects_from_requirement, OBJECT_LABEL_TO_API

CACHE_DIR = Path(__file__).parent.parent / ".fields_cache"


def _get_project_cache_dir(project_name: str | None) -> Path:
    """按项目分目录：.fields_cache/项目名/，未配置项目则用根目录。"""
    if project_name and project_name.strip():
        return CACHE_DIR / project_name.strip()
    return CACHE_DIR


# ── 缓存读写 ──────────────────────────────────────────────────────────────────

def get_cache_path(object_api: str, project_name: str | None = None) -> Path:
    """返回字段缓存文件路径。project_name 为空时使用 .fields_cache 根目录（兼容旧结构）。"""
    base = _get_project_cache_dir(project_name)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{object_api}.yml"


def get_options_override_path(object_api: str, project_name: str | None = None) -> Path:
    """选项覆盖文件路径：.fields_cache/项目/AccountObj_options.yml"""
    base = _get_project_cache_dir(project_name)
    return base / f"{object_api}_options.yml"


def get_supplement_path(object_api: str, project_name: str | None = None) -> Path:
    """补充字段文件路径：.fields_cache/项目/AccountObj_supplement.yml，用于手动添加缓存中缺失的字段。"""
    base = _get_project_cache_dir(project_name)
    return base / f"{object_api}_supplement.yml"


def load_cache(object_api: str, project_name: str | None = None) -> list | None:
    """读取缓存，返回字段列表；未命中返回 None。
    若配置了 project_name，先查项目目录，再回退到根目录。
    若存在 {object_api}_options.yml，将其中的选项合并到对应字段。
    若主缓存不存在但存在 _supplement.yml，则仅用 supplement 作为字段来源。"""
    # 优先项目目录
    path = get_cache_path(object_api, project_name)
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        fields = data.get("fields") or []
    else:
        # 兼容：未配置项目或项目目录无缓存时，查根目录
        if project_name and project_name.strip():
            fallback = get_cache_path(object_api, None)
            if fallback.exists():
                data = yaml.safe_load(fallback.read_text(encoding="utf-8")) or {}
                fields = data.get("fields") or []
            else:
                fields = []
        else:
            fields = []
        if not fields:
            supp_path = get_supplement_path(object_api, project_name)
            if not supp_path.exists() and project_name and project_name.strip():
                supp_path = get_supplement_path(object_api, None)
            if supp_path.exists():
                supp_data = yaml.safe_load(supp_path.read_text(encoding="utf-8")) or {}
                add_list = supp_data.get("add_fields") or supp_data.get("fields") or []
                fields = [{"api": i.get("api", ""), "label": i.get("label", i.get("api", ""))}
                         for i in add_list if isinstance(i, dict) and i.get("api")]
                if fields:
                    print(f"  [字段抓取] 使用 supplement 作为字段来源: {supp_path.name}")
            if not fields:
                return None

    opts_path = get_options_override_path(object_api, project_name)
    if not opts_path.exists() and project_name and project_name.strip():
        opts_path = get_options_override_path(object_api, None)
    if opts_path.exists():
        overrides = yaml.safe_load(opts_path.read_text(encoding="utf-8")) or {}
        api_to_opts = {k: v for k, v in overrides.items() if isinstance(v, list)}
        for f in fields:
            api = f.get("api", "")
            if api in api_to_opts:
                f["options"] = [
                    {"label": str(o.get("label", "")), "value": str(o.get("value", ""))}
                    for o in api_to_opts[api]
                    if isinstance(o, dict) and o.get("value") is not None
                ]

    supp_path = get_supplement_path(object_api, project_name)
    if not supp_path.exists() and project_name and project_name.strip():
        supp_path = get_supplement_path(object_api, None)
    if supp_path.exists():
        supp_data = yaml.safe_load(supp_path.read_text(encoding="utf-8")) or {}
        add_list = supp_data.get("add_fields") or supp_data.get("fields") or []
        existing_apis = {f.get("api", "") for f in fields}
        for item in add_list:
            if isinstance(item, dict):
                api = item.get("api", "").strip()
                if api and api not in existing_apis:
                    fields.append({"api": api, "label": item.get("label", api)})
                    existing_apis.add(api)
        if add_list:
            print(f"  [字段抓取] 已合并 supplement 补充字段: {supp_path.name}")
    return fields


def save_cache(object_api: str, fields: list, project_name: str | None = None):
    """写入字段缓存。project_name 为空时写入 .fields_cache 根目录。"""
    path = get_cache_path(object_api, project_name)
    path.write_text(yaml.dump({"fields": fields}, allow_unicode=True), encoding="utf-8")
    print(f"  [字段抓取] 缓存已写入 ({len(fields)} 个字段): {path}")


def _parse_field_options(f: dict) -> list | None:
    """从原始字段解析 options，返回 [{label, value}]，无选项则返回 None。"""
    opts = f.get("options") or f.get("optionList") or []
    if not opts:
        return None
    result = []
    for o in opts:
        if isinstance(o, dict):
            label = o.get("label") or o.get("name") or ""
            value = o.get("value") if "value" in o else o.get("id")
            if value is not None:
                result.append({"label": str(label), "value": str(value)})
        elif isinstance(o, (list, tuple)) and len(o) >= 2:
            result.append({"label": str(o[0]), "value": str(o[1])})
    return result if result else None


def fields_to_prompt_text(object_api: str, object_label: str, fields: list) -> str:
    """将字段列表转换为 LLM prompt 文本段落。含 options 时增加选项列（label=value）。"""
    if not fields:
        return ""
    has_options = any(f.get("options") for f in fields)
    lines = [f"### {object_label}（{object_api}）字段列表（使用真实 API 名，不要猜测）"]
    if has_options:
        lines.append("| 字段标签 | API 名 | 选项（label=value，QueryOperator 用 value） |")
        lines.append("|---------|--------|------------------------------------------|")
        for f in fields:
            opts = f.get("options")
            opts_str = ", ".join(f"{o['label']}={o['value']}" for o in opts) if opts else ""
            lines.append(f"| {f.get('label', '')} | {f.get('api', '')} | {opts_str} |")
    else:
        lines.append("| 字段标签 | API 名 |")
        lines.append("|---------|--------|")
        for f in fields:
            lines.append(f"| {f.get('label', '')} | {f.get('api', '')} |")
    return "\n".join(lines)


# ── DOM 抓取策略 ──────────────────────────────────────────────────────────────

def _extract_via_js(page) -> list:
    """JS 多策略提取：表格行 → 列表项 → 含 __ 的文本行。"""
    return page.evaluate("""
        () => {
            const isApiName = s =>
                s && (s.includes('__') || /^[A-Z][a-zA-Z]+Obj$/.test(s)
                      || s === '_id' || s === 'name');

            // 策略1: <tr> 两列表格
            const rows = [...document.querySelectorAll('tr')];
            const tableFields = [];
            for (const row of rows) {
                const cells = [...row.querySelectorAll('td')];
                if (cells.length < 2) continue;
                const [a, b] = [cells[0].innerText.trim(), cells[1].innerText.trim()];
                if (isApiName(b) && a) tableFields.push({label: a, api: b});
                else if (isApiName(a) && b) tableFields.push({label: b, api: a});
            }
            if (tableFields.length > 3) return tableFields;

            // 策略2: 找包含 __c 或 __C 的容器，按行解析
            const panels = [...document.querySelectorAll(
                '[class*="field"], [class*="api"], [class*="Field"], [class*="Api"]'
            )].filter(el => el.innerText && el.innerText.includes('__'));

            for (const panel of panels) {
                const lines = panel.innerText.split('\\n').map(l => l.trim()).filter(Boolean);
                const parsed = [];
                for (let i = 0; i < lines.length - 1; i++) {
                    const cur = lines[i], next = lines[i + 1];
                    if (isApiName(next) && !isApiName(cur)) {
                        parsed.push({label: cur, api: next});
                        i++;  // skip next
                    } else if (isApiName(cur) && !isApiName(next)) {
                        parsed.push({label: next, api: cur});
                        i++;
                    }
                }
                if (parsed.length > 3) return parsed;
            }

            // 策略3: 直接扫描所有文本，找相邻"标签\tAPI"对
            const allText = document.body.innerText;
            const lineFields = [];
            for (const line of allText.split('\\n')) {
                const parts = line.trim().split(/\\s{2,}|\\t/);
                if (parts.length >= 2) {
                    const [a, b] = [parts[0].trim(), parts[1].trim()];
                    if (isApiName(b) && a.length > 0 && a.length < 30)
                        lineFields.push({label: a, api: b});
                    else if (isApiName(a) && b.length > 0 && b.length < 30)
                        lineFields.push({label: b, api: a});
                }
            }
            // 过滤重复
            const seen = new Set();
            return lineFields.filter(f => {
                if (seen.has(f.api)) return false;
                seen.add(f.api);
                return true;
            });
        }
    """) or []


def _scrape_field_tab(page) -> list:
    """点击「字段API对照表」标签页后抓取所有字段。滚动表格以加载虚拟化行。"""
    try:
        tab = page.locator(':text("字段API对照表")').first
        tab.wait_for(state="visible", timeout=8000)
        tab.click()
        time.sleep(2)
        print("  [字段抓取] 已切换到「字段API对照表」标签")
    except Exception as e:
        print(f"  [字段抓取] 标签页切换失败: {e}")
        return []

    for _ in range(5):
        page.evaluate("""
            () => {
                const scrollables = document.querySelectorAll('[class*="scroll"], .el-table__body-wrapper, [class*="table"]');
                scrollables.forEach(el => {
                    if (el.scrollHeight > el.clientHeight) {
                        el.scrollTop = el.scrollHeight;
                    }
                });
            }
        """)
        time.sleep(0.5)

    fields = _extract_via_js(page)
    print(f"  [字段抓取] 提取到 {len(fields)} 个字段")
    return fields


# ── 表单填写（打开编辑器用）────────────────────────────────────────────────────

def _fill_temp_form(page, object_label: str, namespace: str, cfg: dict):
    """快速填写「新建自定义APL函数」表单，只为打开编辑器查看字段。"""
    temp_name = "FetchFieldsTemp"

    # 代码名称：用 elementFromPoint 找对话框内的 input（未被模态遮罩挡住的 input）
    # 背景 input 被 ui-mask/modal-overlay 挡住，elementFromPoint 返回遮罩元素而非 input
    code_idx = page.evaluate("""
        () => {
            const all = [...document.querySelectorAll('input[type="text"]:not([readonly])')];
            for (let i = 0; i < all.length; i++) {
                const r = all[i].getBoundingClientRect();
                if (r.width < 100 || r.height <= 0) continue;
                // 检查该位置的最顶层元素是否是这个 input（未被遮挡）
                const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
                const top = document.elementFromPoint(cx, cy);
                if (top && (top === all[i] || all[i].contains(top) || top.contains(all[i]))) {
                    return i;
                }
            }
            return -1;
        }
    """)
    if code_idx >= 0:
        try:
            code_input = page.locator('input[type="text"]:not([readonly])').nth(code_idx)
            code_input.click()
            code_input.fill(temp_name)
            print(f"  [字段抓取] 代码名称已填写 (index={code_idx}): {temp_name}")
        except Exception as e:
            print(f"  [字段抓取] 代码名称填写失败: {e}")
    else:
        print("  [字段抓取] 代码名称 input 未找到")
    time.sleep(0.3)

    # 命名空间
    from deployer.deploy import _click_select_option
    ns_result = _click_select_option(page, "命名空间", namespace)
    if ns_result and "not_found" in ns_result:
        try:
            first_option = ns_result.split("options=")[-1].split("|")[0].strip()
            if first_option:
                print(f"  [字段抓取] 命名空间 '{namespace}' 未找到，改用: {first_option}")
                _click_select_option(page, "命名空间", first_option)
        except Exception:
            pass

    # 绑定对象
    if object_label:
        try:
            obj_result = _click_select_option(page, "绑定对象", object_label)
            if obj_result and "not_found" in obj_result:
                print(f"  [字段抓取] 绑定对象 '{object_label}' 未找到，请检查对象标签名")
        except Exception as e:
            print(f"  [字段抓取] 选择绑定对象失败: {e}")

    time.sleep(0.3)

    # Api Name：最后点自动生成（绑定对象选完后），若仍报错则手动填一个合规名
    import hashlib
    fallback_api_name = f"Fetch{hashlib.md5(temp_name.encode()).hexdigest()[:6].upper()}__c"
    try:
        page.locator(':text("自动生成")').first.click(timeout=3000)
        time.sleep(0.8)
        has_error = page.evaluate("() => document.body.innerText.includes('不符合规则')")
        if has_error:
            page.evaluate(f"""
                () => {{
                    const all = [...document.querySelectorAll('input[type="text"]:not([readonly])')];
                    const dialogInputs = all.filter(el => {{
                        const r = el.getBoundingClientRect();
                        return r.width > 50 && r.height > 0 && r.x > 200;
                    }});
                    const apiInput = dialogInputs.find(i => i.placeholder && i.placeholder.includes('请输入'))
                        || dialogInputs[1];
                    if (apiInput) {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(apiInput, {repr(fallback_api_name)});
                        apiInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                        apiInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)
            time.sleep(0.3)
            print(f"  [字段抓取] Api Name 手动填写: {fallback_api_name}")
        else:
            print("  [字段抓取] Api Name 自动生成 ok")
    except Exception as e:
        print(f"  [字段抓取] Api Name 填写失败: {e}")

    # 描述（必填）
    page.evaluate("""
        () => {
            const ta = document.querySelector('textarea:not([readonly])');
            if (ta) {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value').set;
                setter.call(ta, '__temp__');
                ta.dispatchEvent(new Event('input', {bubbles:true}));
            }
        }
    """)
    time.sleep(0.2)


# ── 在已有 page 中抓取（复用浏览器，供批量模式等）──────────────────────────────

def _fetch_fields_in_page(page, object_label: str, namespace: str, cfg: dict) -> list:
    """在已有 page（需已在函数列表页）中打开编辑器并抓取字段，不新建浏览器。"""
    fields = []
    try:
        print("  [字段抓取] 在已有页面中打开「新建APL函数」...")
        page.wait_for_selector(':text("新建APL函数")', timeout=15000)
        page.locator(':text("新建APL函数")').first.click()
        page.wait_for_selector(':text("新建自定义APL函数")', timeout=10000)
        time.sleep(0.5)

        _fill_temp_form(page, object_label, namespace, cfg)
        time.sleep(0.3)

        try:
            btn = page.locator(':text("下一步")').last
            bbox = btn.bounding_box(timeout=5000)
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
            else:
                btn.click(force=True, timeout=5000)
        except Exception as e:
            print(f"  [字段抓取] 点击下一步失败: {e}")
        time.sleep(2)

        try:
            tmpl = page.locator(':text("使用空模板")').first
            tmpl.wait_for(state="visible", timeout=8000)
            tmpl.click()
            time.sleep(1)
        except Exception:
            pass

        print("  [字段抓取] 等待编辑器加载...")
        page.wait_for_selector(':text-is("保存草稿")', timeout=30000)
        time.sleep(1.5)

        fields = _scrape_field_tab(page)

        try:
            bbox = page.locator(':text-is("取消")').last.bounding_box(timeout=3000)
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
                time.sleep(0.5)
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
    except Exception as e:
        print(f"  [字段抓取] 页面内抓取失败: {e}")
    return fields


# ── 浏览器抓取主流程 ───────────────────────────────────────────────────────────

def _browser_fetch(object_api: str, object_label: str, namespace: str, cfg: dict) -> list:
    """打开浏览器 → 进入 APL 编辑器 → 抓取字段 → 取消关闭。"""
    from playwright.sync_api import sync_playwright

    fields = []
    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})

        # 恢复登录 session（按项目读取，兼容旧格式）
        from deployer.deploy_login import get_session_path
        session_path = get_session_path(cfg)
        if session_path.exists():
            data = json.loads(session_path.read_text(encoding="utf-8"))
            cookies = data.get("cookies", data) if isinstance(data, dict) else data
            if cookies:
                ctx.add_cookies(cookies)

        page = ctx.new_page()
        base_url = cfg["fxiaoke"]["base_url"].rstrip("/")
        func_path = cfg["fxiaoke"].get("function_path", "/paas/functionList")
        target_url = base_url + func_path

        print(f"  [字段抓取] 导航: {target_url}")
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        # 如果 session 过期，重新登录
        login_path = cfg["fxiaoke"].get("login_path", "/login")
        if login_path in page.url:
            print("  [字段抓取] Session 过期，重新登录...")
            from deployer.deploy import login
            login(page, cfg)
            page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

        # 先尝试 JS 内置 API（无需打开编辑器，只需已在函数列表页）
        quick_fields = _inbrowser_fetch_fields(page, object_api)
        if quick_fields:
            fields = quick_fields
            return fields

        # 设置网络拦截，捕获编辑器加载时的字段 API 响应
        captured_fields: list = []
        import json as _json

        def _on_response(response):
            if captured_fields:
                return
            try:
                url_lower = response.url.lower()
                if not any(k in url_lower for k in ("describe", "field", "metadata")):
                    return
                body = response.json()
                raw = body.get("fields") or (body.get("data") or {}).get("fields") or []
                describe = (body.get("data") or {}).get("describe") or body.get("describe")
                if describe and isinstance(describe.get("fields"), dict):
                    raw = list(describe["fields"].values())
                if len(raw) > 3:
                    parsed = []
                    for f in raw:
                        api = f.get("fieldName") or f.get("apiName") or f.get("api_name") or f.get("api") or ""
                        if not api:
                            continue
                        item = {
                            "label": f.get("label") or f.get("fieldLabel") or f.get("name") or "",
                            "api": api,
                        }
                        opts = _parse_field_options(f)
                        if opts:
                            item["options"] = opts
                        parsed.append(item)
                    if len(parsed) > 3:
                        captured_fields.extend(parsed)
                        print(f"  [字段抓取] 网络拦截到 {len(parsed)} 个字段")
            except Exception:
                pass

        page.on("response", _on_response)

        # 打开「新建APL函数」对话框
        print("  [字段抓取] 打开「新建APL函数」对话框...")
        page.wait_for_selector(':text("新建APL函数")', timeout=15000)
        page.locator(':text("新建APL函数")').first.click()
        page.wait_for_selector(':text("新建自定义APL函数")', timeout=10000)
        time.sleep(0.5)

        # 填写表单（传入正确的 namespace）
        _fill_temp_form(page, object_label, namespace, cfg)
        time.sleep(0.3)

        # 点「下一步」
        try:
            btn = page.locator(':text("下一步")').last
            bbox = btn.bounding_box(timeout=5000)
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
                print("  [字段抓取] 已点击「下一步」")
            else:
                btn.click(force=True, timeout=5000)
                print("  [字段抓取] 已点击「下一步」(force)")
        except Exception as e:
            print(f"  [字段抓取] 点击下一步失败: {e}")
            from deployer.deploy_login import screenshot as _ss
            _ss(page, "fetch_nextstep_fail")
        time.sleep(2)

        # 处理「选择模板」弹窗
        try:
            tmpl = page.locator(':text("使用空模板")').first
            tmpl.wait_for(state="visible", timeout=8000)
            tmpl.click()
            print("  [字段抓取] 已点击「使用空模板」")
            time.sleep(1)
        except Exception as e:
            print(f"  [字段抓取] 未找到「使用空模板」: {e}")
            from deployer.deploy_login import screenshot as _ss
            _ss(page, "fetch_template_fail")

        # 等待编辑器加载，同时检查网络拦截是否已拿到字段
        print("  [字段抓取] 等待编辑器加载...")
        try:
            page.wait_for_selector(':text-is("保存草稿")', timeout=30000)
        except Exception:
            from deployer.deploy_login import screenshot as _ss
            _ss(page, "fetch_editor_timeout")
            if captured_fields:
                print(f"  [字段抓取] 编辑器超时但网络拦截拿到了字段，直接使用")
                fields = captured_fields
                return fields
            raise
        time.sleep(1)

        api_fields = _inbrowser_fetch_fields(page, object_api)
        if captured_fields:
            fields = captured_fields
        else:
            fields = _scrape_field_tab(page)

        if api_fields and len(api_fields) > len(fields or []):
            api_map = {f["api"]: f for f in api_fields}
            for f in (fields or []):
                m = api_map.get(f.get("api"))
                if m and m.get("options") and not f.get("options"):
                    f["options"] = m["options"]
            merged = list(api_fields)
            for f in (fields or []):
                if f.get("api") and not any(m["api"] == f["api"] for m in merged):
                    merged.append(f)
            fields = merged
            print(f"  [字段抓取] describe API 合并后共 {len(fields)} 个字段")
        elif api_fields and (not fields or len(api_fields) >= len(fields)):
            fields = api_fields
            print(f"  [字段抓取] 使用 describe API 结果（{len(fields)} 个字段）")
        elif fields and not any(f.get("options") for f in fields) and api_fields:
            api_map = {f["api"]: f for f in api_fields}
            for f in fields:
                m = api_map.get(f.get("api"))
                if m and m.get("options"):
                    f["options"] = m["options"]
            print(f"  [字段抓取] describe API 补充了选项信息")

        # 取消关闭（不保存）
        try:
            bbox = page.locator(':text-is("取消")').last.bounding_box(timeout=3000)
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
                time.sleep(0.5)
        except Exception:
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass

    except Exception as e:
        print(f"  [字段抓取] 浏览器抓取失败: {e}")
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            if pw:
                pw.stop()
        except Exception:
            pass

    return fields


# ── OpenAPI 方案（首选，无需浏览器）─────────────────────────────────────────

def _openapi_get_corp_access_token(cfg: dict) -> tuple[str, str]:
    """用 permanent_code 换取 corpAccessToken，返回 (token, corpId)。"""
    import urllib.request
    oa = cfg.get("openapi") or {}
    app_id = oa.get("app_id", "")
    app_secret = oa.get("app_secret", "")
    permanent_code = oa.get("permanent_code", "")
    corp_id = oa.get("corp_id", "")
    base_url = (oa.get("base_url") or "https://open.fxiaoke.com").rstrip("/")

    import json as _json
    payload = _json.dumps({
        "appId": app_id,
        "appSecret": app_secret,
        "permanentCode": permanent_code,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/cgi/corpAccessToken/get/V2",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = _json.loads(resp.read().decode())
    if data.get("errorCode") != 0:
        raise RuntimeError(f"获取 corpAccessToken 失败: {data}")
    return data["corpAccessToken"], corp_id


def _inbrowser_fetch_fields(page, object_api: str) -> list:
    """在已登录的浏览器页面内，用 JS fetch 调 fxiaoke 内部 describe API（使用 session cookie，无 IP 限制）。"""
    try:
        result = page.evaluate(f"""
            async () => {{
                const objectApi = {repr(object_api)};
                const base = window.location.origin;
                const tries = [
                    {{ ep: base + '/cgi/crm/v2/object/describe', body: {{ data: {{ apiName: objectApi, includeDetail: true }} }} }},
                    {{ ep: base + '/cgi/crm/v2/object/describe', body: {{ apiName: objectApi, includeDetail: true }} }},
                    {{ ep: '/cgi/crm/v2/object/describe', body: {{ data: {{ apiName: objectApi, includeDetail: true }} }} }},
                    {{ ep: '/cgi/crm/v2/data/describe', body: {{ objectApiName: objectApi }} }},
                    {{ ep: '/cgi/crm/custom/v2/describe', body: {{ apiName: objectApi, objectApiName: objectApi }} }},
                    {{ ep: '/paas/apl/object/describe', body: {{ apiName: objectApi, objectApiName: objectApi }} }},
                ];
                for (const t of tries) {{
                    try {{
                        const resp = await fetch(t.ep, {{
                            method: 'POST',
                            credentials: 'include',
                            headers: {{'Content-Type': 'application/json'}},
                            body: JSON.stringify(t.body)
                        }});
                        const data = await resp.json();
                        let raw = data.fields || (data.data && data.data.fields) || [];
                        const describe = data.data?.describe || data.describe;
                        if (describe?.fields && typeof describe.fields === 'object' && !Array.isArray(describe.fields)) {{
                            raw = Object.values(describe.fields);
                        }}
                        if (raw && raw.length > 3) {{
                            return raw.map(f => {{
                                const opts = f.options || f.optionList || [];
                                const options = opts.length ? opts.map(o => {{
                                    const v = o.value !== undefined ? o.value : o.id;
                                    if (v === undefined) return null;
                                    return {{ label: String(o.label || o.name || ''), value: String(v) }};
                                }}).filter(Boolean) : undefined;
                                return {{
                                    label: f.label || f.fieldLabel || f.name || '',
                                    api: f.fieldName || f.apiName || f.api || '',
                                    ...(options && options.length ? {{ options }} : {{}})
                                }};
                            }}).filter(f => f.api);
                        }}
                    }} catch(e) {{}}
                }}
                return [];
            }}
        """)
        if result and len(result) > 3:
            print(f"  [字段抓取] 浏览器内置 API 获取到 {len(result)} 个字段")
            return result
    except Exception as e:
        print(f"  [字段抓取] 浏览器内置 API 失败: {e}")
    return []


def _openapi_fetch_fields(object_api: str, cfg: dict) -> list:
    """通过纷享销客 OpenAPI 获取对象字段列表，返回 [{label, api}]。"""
    import urllib.request, json as _json
    oa = cfg.get("openapi") or {}
    base_url = (oa.get("base_url") or "https://open.fxiaoke.com").rstrip("/")
    user_id = str(oa.get("current_open_user_id", "1000"))

    try:
        token, corp_id = _openapi_get_corp_access_token(cfg)
    except Exception as e:
        print(f"  [字段抓取] OpenAPI 鉴权失败: {e}")
        return []

    # 先尝试自定义对象接口，再尝试标准对象接口
    endpoints = [
        (f"{base_url}/cgi/crm/custom/v2/describe", {"apiName": object_api}),
        (f"{base_url}/cgi/crm/v2/data/describe", {"objectApiName": object_api}),
    ]
    for url, extra_body in endpoints:
        try:
            body = {"corpAccessToken": token, "corpId": corp_id,
                    "currentOpenUserId": user_id}
            body.update(extra_body)
            req = urllib.request.Request(
                url,
                data=_json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read().decode())
            if data.get("errorCode") != 0:
                continue
            # 解析字段列表
            fields_raw = (
                data.get("fields")
                or (data.get("data") or {}).get("fields")
                or []
            )
            fields = []
            for f in fields_raw:
                api = f.get("fieldName") or f.get("apiName") or f.get("api") or ""
                label = f.get("label") or f.get("fieldLabel") or f.get("name") or api
                if not api:
                    continue
                item = {"label": label, "api": api}
                opts = _parse_field_options(f)
                if opts:
                    item["options"] = opts
                fields.append(item)
            if fields:
                print(f"  [字段抓取] OpenAPI 获取到 {len(fields)} 个字段（{object_api}）")
                return fields
        except Exception as e:
            print(f"  [字段抓取] OpenAPI {url} 失败: {e}")
            continue
    return []


# ── 公开接口 ──────────────────────────────────────────────────────────────────

def _project_from_cfg(cfg: dict) -> str | None:
    """从配置读取项目名（用于字段缓存按项目分目录）。"""
    return (cfg.get("fxiaoke") or {}).get("project_name") or None


def fetch_fields(object_api: str, object_label: str, cfg: dict,
                 namespace: str = "流程", force_refresh: bool = False,
                 project_name: str | None = None, page=None) -> list:
    """获取对象字段列表（优先读缓存，缓存未命中则抓取）。

    抓取优先级：OpenAPI（无需浏览器）→ 浏览器自动化（备用）

    返回 [{"label": "字段标签", "api": "field_api__c"}, ...]
    page: 若提供且缓存未命中，在已有 page 中抓取（复用浏览器）；否则新建浏览器。
    """
    proj = project_name if project_name is not None else _project_from_cfg(cfg)
    if not force_refresh:
        cached = load_cache(object_api, proj)
        if cached is not None:
            print(f"  [字段抓取] 读取缓存 {object_api}: {len(cached)} 个字段")
            return cached

    print(f"  [字段抓取] 开始从平台抓取 {object_api}（{object_label}）的字段...")

    # 首选：OpenAPI（不需要登录，速度快）
    oa_cfg = cfg.get("openapi") or {}
    if oa_cfg.get("app_id") and oa_cfg.get("app_secret") and oa_cfg.get("permanent_code"):
        fields = _openapi_fetch_fields(object_api, cfg)
        if fields:
            save_cache(object_api, fields, proj)
            return fields
        print(f"  [字段抓取] OpenAPI 未返回字段，改用浏览器方案...")

    # 备用：浏览器自动化（page 已存在时先用 JS 内置 API 快速获取）
    if page:
        fields = _inbrowser_fetch_fields(page, object_api)
        if not fields:
            fields = _fetch_fields_in_page(page, object_label, namespace, cfg)
    else:
        fields = _browser_fetch(object_api, object_label, namespace, cfg)
    if fields:
        save_cache(object_api, fields, proj)
    else:
        print(f"  [字段抓取] 未能抓取到字段，请检查对象标签名是否正确")
    return fields


def fetch_fields_for_req(req: dict, cfg: dict, force_refresh: bool = False, page=None) -> dict:
    """从 req.yml 中读取主对象和关联对象，批量抓取字段。

    req.yml 格式：
      object_api: tenant__c
      object_label: 租户
      project: 硅基流动          # 可选；覆盖 config.fxiaoke.project_name，缓存按项目分目录
      namespace: 流程            # 用于打开编辑器时选择命名空间（与部署时一致）
      related_objects:           # 可选；若为空则从 requirement 中自动推断
        - api: AccountObj
          label: 客户

    返回 {object_api: [fields]}
    """
    result = {}
    namespace = req.get("namespace", "流程")

    # 项目名：req.yml > config.fxiaoke.project_name
    proj = req.get("project") or _project_from_cfg(cfg) or None
    if proj:
        print(f"  [字段抓取] 项目: {proj}（缓存目录: .fields_cache/{proj}/）")

    # 主对象
    obj_api = req.get("object_api", "")
    obj_label = req.get("object_label", "")
    if obj_api and obj_label:
        fields = fetch_fields(obj_api, obj_label, cfg,
                              namespace=namespace, force_refresh=force_refresh,
                              project_name=proj, page=page)
        if fields:
            result[obj_api] = fields

    # 关联对象：优先用 req 中配置，否则从需求文本推断
    related_list = req.get("related_objects") or []
    if not related_list and req.get("requirement"):
        inferred = infer_related_objects_from_requirement(
            req["requirement"], obj_api, obj_label
        )
        if inferred:
            related_list = inferred
            print(f"  [字段抓取] 从需求推断关联对象: {[r['label'] for r in inferred]}")

    for related in related_list:
        r_api = related.get("api", "")
        r_label = related.get("label", "")
        if r_api and r_label:
            fields = fetch_fields(r_api, r_label, cfg,
                                  namespace=namespace, force_refresh=force_refresh,
                                  project_name=proj, page=page)
            if fields:
                result[r_api] = fields

    return result


def build_fields_context(fields_map: dict, req: dict) -> str:
    """将字段映射转换为 LLM prompt 的上下文文本段。"""
    if not fields_map:
        return ""
    sections = [
        "## 对象字段 API 名（必须使用）\n",
        "**仅使用下方列表中的 API 名，禁止猜测或使用未列出的字段。**\n",
        "需求中的字段名与列表「字段标签」列对应，用「API 名」列的值。例如需求说「近一个月回款」且列表有「近一个月回款 | recent_month_receipt__c」，则必须用 recent_month_receipt__c，禁止用中文或占位描述。\n",
        "若需求中的字段在列表中不存在：必须用占位符 `TODO_REPLACE_XXX` 并注释 `// 待确认：xxx 字段 API 名需在平台对象管理中查看后替换`。\n",
    ]
    obj_labels = {req.get("object_api", ""): req.get("object_label", "")}
    for related in req.get("related_objects", []):
        obj_labels[related.get("api", "")] = related.get("label", "")

    # 未在 related_objects 中的对象（如自动推断的）用 OBJECT_LABEL_TO_API 反查
    reverse = {v: k for k, v in OBJECT_LABEL_TO_API.items()}
    for obj_api in fields_map:
        if obj_api not in obj_labels:
            obj_labels[obj_api] = reverse.get(obj_api, obj_api)

    for obj_api, fields in fields_map.items():
        label = obj_labels.get(obj_api, obj_api)
        sections.append(fields_to_prompt_text(obj_api, label, fields))
        sections.append("")

    return "\n".join(sections)


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="字段 API 名抓取器")
    parser.add_argument("--object-api", dest="object_api", required=True, help="对象 API 名")
    parser.add_argument("--object-label", dest="object_label", required=True, help="对象中文标签名")
    parser.add_argument("--namespace", default="流程", help="命名空间（默认: 流程）")
    parser.add_argument("--project", dest="project_name", default=None,
                        help="项目名（覆盖 config 中的 project_name，缓存按项目分目录）")
    parser.add_argument("--force", action="store_true", help="强制刷新缓存")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    fields = fetch_fields(args.object_api, args.object_label, cfg,
                          namespace=args.namespace, force_refresh=args.force,
                          project_name=args.project_name)
    if fields:
        print(f"\n字段列表（共 {len(fields)} 个）：")
        for f in fields:
            print(f"  {f.get('label', '?'):20s}  {f.get('api', '?')}")
    else:
        print("未能获取字段列表")


if __name__ == "__main__":
    main()
