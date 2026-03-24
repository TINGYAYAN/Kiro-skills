"""
APL 函数部署器 —— 通过 Playwright 浏览器自动化将 APL 代码部署到纷享销客。

用法：
  python deploy.py --file /path/to/function.apl --func-name "函数名称"
  python deploy.py --file /path/to/function.apl --func-name "函数名称" --headless
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from deployer import selectors as sel
from deployer.deploy_login import (
    navigate_to_function_list,
    get_frame,
    save_cookies,
    load_cookies,
    screenshot,
    wait_for_manual_login,
    dismiss_stale_apl_modals,
)
from utils import load_config

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)


def _get_search_input_locator(frame):
    """获取函数列表搜索框 locator，尝试多个选择器。"""
    selectors = [sel.FUNC_SEARCH_INPUT] + getattr(sel, "FUNC_SEARCH_INPUT_ALT", [])
    selectors = list(dict.fromkeys(selectors))  # 去重
    for s in selectors:
        try:
            loc = frame.locator(s).first
            loc.wait_for(timeout=5000)
            return loc
        except Exception:
            continue
    return None


def find_function(frame, func_name: str) -> bool:
    """在函数列表中搜索函数名，返回是否找到。"""
    try:
        search_loc = _get_search_input_locator(frame)
        if not search_loc:
            raise RuntimeError("未找到函数列表搜索框")
        search_loc.fill("")
        search_loc.fill(func_name)
        frame.keyboard.press("Enter")
        # 等待搜索结果刷新，结果出现即返回
        try:
            frame.wait_for_function(
                f"""() => [...document.querySelectorAll('{sel.FUNC_LIST_ITEM}')]
                        .some(el => (el.innerText || '').includes({repr(func_name)}))""",
                timeout=5000
            )
            return True
        except Exception:
            pass
        items = frame.query_selector_all(sel.FUNC_LIST_ITEM)
        for item in items:
            if func_name in (item.inner_text() or ""):
                return True
        return False
    except Exception as e:
        print(f"  [警告] 搜索函数时出错: {e}")
        return False


def _click_select_option(frame, label_text: str, option_text: str):
    """
    纷享销客 el-select：
    - 触发器：div.paasf-form-select 里的 .el-input__inner
    - 下拉弹层：el-select-dropdown.el-popper 被 append 到 body（不在 form 行内）
    策略：
      1. 先找触发器 input 并用 Playwright fill+click 打开下拉（支持过滤）
      2. 在 body 层找打开的 .el-select-dropdown.el-popper，scrollIntoView 后点击 li
      3. 按 Escape 关闭下拉，避免遮挡后续操作
    """
    # ── Step 1：找到 label 对应的触发器 input，用 Playwright 点击打开下拉 ──
    # （先用 JS 找到 input，再用 Playwright locator 操作，更可靠）
    input_index = frame.evaluate(f"""
        () => {{
            const dialog = document.querySelector('.paas-func-dialog') || document.body;
            const walker = document.createTreeWalker(dialog, NodeFilter.SHOW_TEXT,
                {{acceptNode: n => n.textContent.trim() === {repr(label_text)}
                    ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP}});
            const node = walker.nextNode();
            if (!node) return -1;
            let p = node.parentElement;
            for (let i=0; i<8; i++) {{
                if (!p || p===dialog) break;
                const inp = p.querySelector('.paasf-form-select .el-input__inner');
                if (inp) {{
                    // 返回该 input 在页面所有 .el-input__inner 中的下标
                    const all = [...document.querySelectorAll('.el-input__inner')];
                    return all.indexOf(inp);
                }}
                p = p.parentElement;
            }}
            return -1;
        }}
    """)

    if input_index >= 0:
        trigger = frame.locator('.el-input__inner').nth(input_index)
        trigger.click()          # 打开下拉
        time.sleep(0.3)
        # 若为 filterable，输入过滤；过滤可能不生效（如 自定义控制器 在分组内），Step2 会滚动查找
        try:
            trigger.fill(option_text)
        except Exception:
            pass
        time.sleep(0.3)
    else:
        print(f"  [警告] 未找到 {label_text} 触发器")
        return

    # ── Step 2：在 body 层找打开的 el-select-dropdown，scrollIntoView 后点 li ──
    # 支持分组下拉（如 平台>自定义控制器），选项可能在 el-select-group__wrap 内
    result = frame.evaluate(f"""
        (function() {{
            const poppers = [...document.querySelectorAll('.el-select-dropdown.el-popper')];
            const open = poppers.find(p => p.offsetHeight > 0);
            if (!open) return 'no_open_popper';

            // 先滚动下拉容器到底部，确保分组内选项都加载（如 平台>自定义控制器）
            const wrap = open.querySelector('.el-select-dropdown__wrap');
            if (wrap) {{
                wrap.scrollTop = wrap.scrollHeight;
            }}

            const items = [...open.querySelectorAll('li.el-select-dropdown__item')];
            let target = items.find(li => li.textContent.trim() === {repr(option_text)})
                      || items.find(li => li.textContent.trim().includes({repr(option_text)}));
            if (!target) {{
                return 'not_found. options=' + items.slice(0,16).map(l=>l.textContent.trim()).join('|');
            }}
            target.scrollIntoView({{block:'nearest'}});
            ['mousedown','mouseup','click'].forEach(t =>
                target.dispatchEvent(new MouseEvent(t, {{bubbles:true, cancelable:true, view:window}}))
            );
            return 'ok:' + target.textContent.trim();
        }})()
    """)
    # 若过滤后未找到（如 自定义控制器 在分组内、过滤行为不一致），清除过滤重试
    if isinstance(result, str) and result.startswith("not_found"):
        try:
            trigger = frame.locator('.el-input__inner').nth(input_index)
            trigger.click()
            time.sleep(0.2)
            trigger.press("Control+a")
            trigger.press("Backspace")
            time.sleep(0.5)
            result = frame.evaluate(f"""
                (function() {{
                    const open = [...document.querySelectorAll('.el-select-dropdown.el-popper')]
                        .find(p => p.offsetHeight > 0);
                    if (!open) return 'no_open_popper';
                    const wrap = open.querySelector('.el-select-dropdown__wrap');
                    if (wrap) wrap.scrollTop = 0;
                    const items = [...open.querySelectorAll('li.el-select-dropdown__item')];
                    let target = items.find(li => li.textContent.trim() === {repr(option_text)})
                              || items.find(li => li.textContent.trim().includes({repr(option_text)}));
                    if (!target) return 'not_found. options=' + items.slice(0,16).map(l=>l.textContent.trim()).join('|');
                    target.scrollIntoView({{block:'nearest'}});
                    ['mousedown','mouseup','click'].forEach(t =>
                        target.dispatchEvent(new MouseEvent(t, {{bubbles:true, cancelable:true, view:window}}))
                    );
                    return 'ok:' + target.textContent.trim();
                }})()
            """)
        except Exception as e:
            print(f"  [部署器] 清除过滤重试失败: {e}")

    print(f"  [部署器] {label_text} → {option_text}: {result}")
    time.sleep(0.2)

    # ── Step 3：按 Escape 确保下拉关闭，不遮挡后续操作 ──
    frame.keyboard.press("Escape")
    time.sleep(0.2)
    return result


def _handle_editor_mode_dialog(frame, page):
    """处理「选择编辑器/编译器」弹窗（新建/编辑时偶尔出现）：选 Code Editor 后点确定。"""
    try:
        # 支持「选择编辑器」或「选择编译器」两种文案
        editor_title = frame.locator('text=/选择编辑|选择编译/').first
        editor_title.wait_for(state="visible", timeout=5000)
        time.sleep(0.5)
        # 选 Code Editor（或「代码编辑器」）
        for opt_text in ["Code Editor", "代码编辑器"]:
            try:
                opt = frame.locator(f':text("{opt_text}")').first
                bbox = opt.bounding_box(timeout=2000)
                if bbox:
                    page.mouse.click(bbox['x'] + bbox['width'] / 2,
                                     bbox['y'] + bbox['height'] / 2)
                    break
            except Exception:
                continue
        time.sleep(0.5)
        ok_btn = frame.locator(':text-is("确定")').last
        ok_bbox = ok_btn.bounding_box(timeout=3000)
        if ok_bbox:
            page.mouse.click(ok_bbox['x'] + ok_bbox['width'] / 2,
                             ok_bbox['y'] + ok_bbox['height'] / 2)
        else:
            ok_btn.click(force=True)
        print("  [部署器] 已处理「选择编辑器」弹窗，选择 Code Editor")
        time.sleep(1)
    except Exception:
        pass  # 没有弹出该对话框，直接继续


def _parse_binding_object_from_apl(apl_path_or_code) -> str:
    """从 APL 文件头解析 @bindingObjectLabel，流程/工作流函数必填。"""
    import re as _re
    try:
        if Path(apl_path_or_code).exists():
            text = Path(apl_path_or_code).read_text(encoding="utf-8")[:2000]
        else:
            text = str(apl_path_or_code)[:2000]
        m = _re.search(r'@bindingObjectLabel\s+([^\n*@]+)', text)
        if m:
            label = m.group(1).strip()
            if label and label not in ("--", "NONE", "无"):
                return label
    except Exception:
        pass
    return ""


def create_function(frame, func_name: str, apl_code: str,
                    namespace: str = "公共库", object_label: str = "",
                    description: str = "", cfg: dict = None, output_file: str = None,
                    req: dict = None):
    """新建函数：填写第一步表单 → 下一步 → 填写代码 → 保存。"""
    print(f"[部署器] 新建函数: {func_name}")

    root = getattr(frame, "page", None) or frame
    try:
        dismiss_stale_apl_modals(root)
    except Exception:
        pass

    # 点击「新建APL函数」按钮（尝试多个选择器，按钮可能在页面下方需滚动）
    frame.evaluate("window.scrollTo(0, 0)")
    time.sleep(0.5)
    btn_loc = None
    for sel_btn in [sel.FUNC_NEW_BTN] + getattr(sel, "FUNC_NEW_BTN_ALT", []):
        try:
            loc = frame.locator(sel_btn).first
            loc.wait_for(timeout=4000)
            if loc.count() > 0:
                loc.scroll_into_view_if_needed(timeout=2000)
                btn_loc = loc
                break
        except Exception:
            continue
    if not btn_loc:
        # 最后尝试：任何包含「新建」或「APL」的可点击元素
        try:
            for txt in ["新建APL", "新建函数", "新建"]:
                loc = frame.get_by_role("button", name=txt)
                if loc.count() > 0:
                    loc.first.scroll_into_view_if_needed(timeout=2000)
                    btn_loc = loc.first
                    break
        except Exception:
            pass
    if not btn_loc:
        raise RuntimeError("未找到「新建APL函数」按钮，可能未登录或页面未加载完成。可用 PWDEBUG=1 打开 Inspector 查看页面结构。")
    btn_loc.click()

    # 等弹窗标题出现（"新建自定义APL函数"）
    frame.wait_for_selector(':text("新建自定义APL函数")', timeout=10000)
    time.sleep(0.3)

    # 填写「代码名称」—— 用 JS 找到"代码名称"文字节点旁边的 input，
    # 触发 Vue 响应式（需要用 native value setter）
    result = frame.evaluate(f"""
        () => {{
            function fillInput(el, val) {{
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(el, val);
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
            }}

            // 1. 找"代码名称"文字节点，从它的父元素向上找 input
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT,
                {{acceptNode: n => n.textContent.trim() === '代码名称'
                    ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP}}
            );
            const labelNode = walker.nextNode();
            if (labelNode) {{
                let parent = labelNode.parentElement;
                for (let i = 0; i < 6; i++) {{
                    const inp = parent.querySelector('input[type="text"]:not([readonly])');
                    if (inp) {{ fillInput(inp, {repr(func_name)}); return 'by_label'; }}
                    parent = parent.parentElement;
                    if (!parent) break;
                }}
            }}

            // 2. fallback：找弹窗内第一个可见、无 placeholder 的 text input
            const all = [...document.querySelectorAll('input[type="text"]:not([readonly])')];
            const visible = all.filter(el => {{
                const r = el.getBoundingClientRect();
                return r.width > 100 && r.height > 0;
            }});
            const target = visible.find(el => !el.placeholder && !el.value) || visible[0];
            if (target) {{ fillInput(target, {repr(func_name)}); return 'by_fallback'; }}
            return 'not_found';
        }}
    """)
    print(f"  [部署器] 代码名称填写: {result}")
    if result == "not_found":
        raise RuntimeError("找不到「代码名称」输入框")

    time.sleep(0.2)

    # 选择「命名空间」
    _click_select_option(frame, "命名空间", namespace)

    # 点击「自动生成」填写 Api Name，若格式报错则手动填一个合规名
    try:
        frame.locator(':text("自动生成")').first.click(timeout=5000)
        time.sleep(0.8)
        # 检查是否出现"不符合规则"错误
        has_error = frame.evaluate("""
            () => document.body.innerText.includes('不符合规则')
        """)
        if has_error:
            # 生成合规名：Proc_ + func_name 前5个ASCII字母 + __c
            import hashlib
            suffix = hashlib.md5(func_name.encode()).hexdigest()[:5].upper()
            api_name = f"Proc_{suffix}__c"
            frame.evaluate(f"""
                () => {{
                    const dialog = document.querySelector('[class*="paas-func-dialog"]') || document.body;
                    const inputs = [...dialog.querySelectorAll('input')];
                    // Api Name 输入框有 placeholder="请输入"
                    const apiInput = inputs.find(i => i.placeholder && i.placeholder.includes('请输入'));
                    if (apiInput) {{
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(apiInput, {repr(api_name)});
                        apiInput.dispatchEvent(new Event('input', {{bubbles: true}}));
                        apiInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                    }}
                }}
            """)
            time.sleep(0.3)
            print(f"  [部署器] Api Name 重新填写: {api_name}")
        else:
            print("  [部署器] Api Name 已自动生成")
    except Exception as e:
        print(f"  [警告] 自动生成 Api Name 失败: {e}")

    # 选择「绑定对象」（流程函数必填）
    if object_label:
        result = _click_select_option(frame, "绑定对象", object_label)
        if result and result.startswith("not_found"):
            # 下拉找不到选项时，打印可用选项并抛出明确错误，避免继续走下去被表单拦截
            raise RuntimeError(
                f"「绑定对象」下拉框找不到「{object_label}」。\n"
                f"可用选项：{result}\n"
                f"请检查 req.yml 里的 object_label 是否与纷享销客对象中文名一致。"
            )

    # 填写「描述」（必填）
    if not description:
        description = func_name  # 至少填函数名作为描述
    desc_result = frame.evaluate(f"""
        () => {{
            const dialog = document.querySelector('.paas-func-dialog') || document.body;
            const walker = document.createTreeWalker(dialog, NodeFilter.SHOW_TEXT,
                {{acceptNode: n => n.textContent.trim() === '描述'
                    ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP}});
            const node = walker.nextNode();
            if (!node) return 'no_label';
            let p = node.parentElement;
            for (let i=0; i<8; i++) {{
                if (!p || p===dialog) break;
                const ta = p.querySelector('textarea');
                if (ta) {{
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value').set;
                    setter.call(ta, {repr(description)});
                    ta.dispatchEvent(new Event('input', {{bubbles: true}}));
                    ta.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return 'ok';
                }}
                p = p.parentElement;
            }}
            return 'not_found';
        }}
    """)
    print(f"  [部署器] 描述填写: {desc_result}")

    time.sleep(0.3)

    # 点「下一步」→ 可能出现「选择模板」弹窗 → 点「使用空模板」
    next_btn = frame.locator(sel.FUNC_NEXT_BTN).first
    next_btn.wait_for(state="visible", timeout=8000)
    next_btn.click()

    page = getattr(frame, 'page', frame)
    # 点「使用空模板」（弹窗加载可能很慢，等待 20 秒）
    # 用 bounding_box + mouse.click 穿透 Shadow DOM，避免 .click() 不生效导致 toast 报错
    for retry in range(2):
        try:
            empty_tmpl = frame.locator(':text("使用空模板")').first
            empty_tmpl.wait_for(state="visible", timeout=20000)
            bbox = empty_tmpl.bounding_box(timeout=5000)
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
                print("  [部署器] 已选择使用空模板（坐标点击）")
            else:
                empty_tmpl.click(force=True)
                print("  [部署器] 已选择使用空模板（force click）")
            break
        except Exception as e:
            if retry == 0:
                print(f"  [部署器] 等待「使用空模板」超时，2 秒后重试: {e}")
                time.sleep(2)
            else:
                print(f"  [警告] 未找到「使用空模板」按钮（可能无模板弹窗）: {e}")

    # 新建时可能弹出「选择编辑器」对话框，需先处理才能进入代码编辑器
    _handle_editor_mode_dialog(frame, page)

    # 等编辑器加载完成：「保存草稿」出现 + 代码编辑器容器出现
    print("  [部署器] 等待编辑器加载...")
    frame.wait_for_selector(':text-is("保存草稿")', timeout=40000)
    try:
        frame.wait_for_selector('.ace_editor, .monaco-editor, .CodeMirror, [class*="code-editor"]',
                                timeout=5000)
    except Exception:
        pass

    _fill_code_and_save(frame, apl_code, cfg=cfg, output_file=output_file,
                        func_name=func_name, req=req)


def update_function(frame, func_name: str, apl_code: str,
                    cfg: dict = None, output_file: str = None, req: dict = None):
    """找到已有函数，点击编辑进入编辑页。
    Element UI 固定列表格会把函数名列和操作列渲染在两个独立的 <table> 里，
    不能在同一个 <tr> 里同时找到函数名和「编辑」按钮。
    策略：先用函数名确定行的 Y 坐标，再在全局找 Y 坐标匹配的「编辑」按钮。
    """
    print(f"[部署器] 更新函数: {func_name}")
    page = getattr(frame, 'page', frame)

    # 1. 找到含函数名的行，获取其 Y 坐标范围
    rows = frame.locator(sel.FUNC_LIST_ITEM).all()
    row_y_center = None
    for row in rows:
        if func_name not in (row.inner_text() or ""):
            continue
        try:
            bbox = row.bounding_box(timeout=2000)
            if bbox:
                row_y_center = bbox['y'] + bbox['height'] / 2
                print(f"  [部署器] 找到函数行，Y 中心: {row_y_center:.0f}")
                break
        except Exception:
            pass

    if row_y_center is None:
        raise RuntimeError(f"找不到函数「{func_name}」的行")

    # 2. 在全局找所有「编辑」按钮，点击 Y 坐标最近的那个
    edit_locs = frame.locator(sel.FUNC_EDIT_LINK).all()
    print(f"  [调试] 全局「编辑」按钮数: {len(edit_locs)}")

    best_bbox = None
    best_dist = float('inf')
    for loc in edit_locs:
        try:
            b = loc.bounding_box(timeout=1000)
            if b:
                dist = abs((b['y'] + b['height'] / 2) - row_y_center)
                if dist < best_dist:
                    best_dist = dist
                    best_bbox = b
        except Exception:
            pass

    if best_bbox and best_dist < 40:  # 40px 以内认为是同一行
        page.mouse.click(best_bbox['x'] + best_bbox['width'] / 2,
                         best_bbox['y'] + best_bbox['height'] / 2)
        print(f"  [部署器] 已点击编辑按钮（Y 偏差: {best_dist:.1f}px）")

        # 编辑会先弹出「元信息编辑」弹窗（与新建相同的表单），需点「下一步」才能进代码编辑器
        try:
            next_btn = frame.locator(sel.FUNC_NEXT_BTN).first
            next_btn.wait_for(state="visible", timeout=10000)
            next_btn_bbox = next_btn.bounding_box(timeout=3000)
            if next_btn_bbox:
                page.mouse.click(next_btn_bbox['x'] + next_btn_bbox['width'] / 2,
                                 next_btn_bbox['y'] + next_btn_bbox['height'] / 2)
            else:
                next_btn.click(force=True)
            print("  [部署器] 元信息弹窗已点「下一步」")
            time.sleep(0.5)
        except Exception as e:
            print(f"  [部署器] 未检测到「下一步」弹窗（可能已直接进入编辑器）: {e}")

        # 编辑已有函数时可能弹出「选择编辑器」对话框，选 Code Editor 后点确定
        _handle_editor_mode_dialog(frame, page)

        _fill_code_and_save(frame, apl_code, cfg=cfg, output_file=output_file,
                            func_name=func_name, req=req)
        return

    raise RuntimeError(f"找不到函数「{func_name}」的编辑入口（全局「编辑」{len(edit_locs)} 个，最近 Y 偏差 {best_dist:.1f}px）")


def _screenshot_frame(frame, name: str):
    """对 frame 所在的 page 截图（Playwright Frame 无 screenshot，通过 .page 获取）。"""
    try:
        # Playwright Frame 对象有 .page 属性指向宿主 Page
        p = getattr(frame, "page", frame)
        screenshot(p, name)
    except Exception:
        pass


def _scrape_fields_from_editor(frame) :
    """在已打开的 APL 编辑器中，点击「字段API对照表」标签，抓取该对象的全部字段。
    返回 [{"label": "字段标签", "api": "field_api__c"}, ...]
    """
    try:
        tab = frame.locator(':text("字段API对照表")').first
        tab.wait_for(state="visible", timeout=5000)
        tab.click()
        # 等表格行出现，而不是固定等待
        try:
            frame.wait_for_selector('table tr, .field-table tr, [class*="field"] tr', timeout=5000)
        except Exception:
            pass
    except Exception as e:
        print(f"  [字段抓取] 标签页切换失败: {e}")
        return []

    from fetcher.fetch_fields import _extract_via_js
    fields = _extract_via_js(frame)
    print(f"  [字段抓取] 编辑器内抓取到 {len(fields)} 个字段")
    return fields


def _fill_code_and_save(frame, apl_code: str, cfg: dict = None,
                        output_file: str = None, func_name: str = "",
                        req: dict = None):
    """向代码编辑器填入代码并保存，之后运行并自动修复错误（若提供 cfg）。
    若提供 req，会在编辑器打开后抓取「字段API对照表」并用真实字段名重新生成代码。
    """
    # 等「保存草稿」按钮出现（编辑器页面独有，不会被聊天控件误匹配）
    frame.wait_for_selector(':text-is("保存草稿")', timeout=35000)
    time.sleep(0.5)

    # ── 读取并保存系统生成的函数 API 名（用于后续精确定位函数）──
    if output_file:
        api_name = _read_func_api_name_from_page(frame)
        if api_name:
            save_func_meta(output_file, {"func_api_name": api_name})
            print(f"  [部署器] 函数 API 名: {api_name}（已保存到 .meta.yml）")

    # ── 抓取字段 API 名并用真实字段名重新生成代码 ──
    if req and cfg:
        try:
            from fetcher.fetch_fields import load_cache, save_cache, build_fields_context, _project_from_cfg
            obj_api = req.get("object_api", "")
            project_name = _project_from_cfg(cfg)

            # 优先使用缓存，避免重复抓取
            cached_fields = load_cache(obj_api, project_name) if obj_api else None
            if cached_fields:
                print(f"  [字段抓取] 使用缓存字段（{len(cached_fields)} 个），跳过重新抓取")
                fields = cached_fields
            else:
                fields = _scrape_fields_from_editor(frame)
                if fields:
                    save_cache(obj_api, fields, project_name)
                    print(f"  [字段抓取] 抓取到 {len(fields)} 个字段，已写入缓存")
                else:
                    print(f"  [字段抓取] 编辑器内未能抓取到字段，将使用原始生成代码继续部署")

            if fields:
                fields_map = {obj_api: fields}
                # 关联对象：优先用 req 配置，否则从需求推断
                related_list = req.get("related_objects") or []
                if not related_list and req.get("requirement"):
                    from utils import infer_related_objects_from_requirement
                    obj_label = req.get("object_label", "")
                    related_list = infer_related_objects_from_requirement(
                        req["requirement"], obj_api, obj_label
                    )
                    if related_list:
                        print(f"  [字段抓取] 从需求推断关联对象: {[r['label'] for r in related_list]}")
                for related in related_list:
                    r_api = related.get("api", "")
                    r_cached = load_cache(r_api, project_name) if r_api else None
                    if r_cached:
                        fields_map[r_api] = r_cached

                try:
                    mf = int((cfg.get("generator") or {}).get("max_fields_in_prompt", 72))
                    fields_context = build_fields_context(
                        fields_map, req, max_fields_per_object=mf
                    )
                except Exception as e:
                    print(f"  [字段抓取] 上下文构建失败: {e}")
                    fields_context = ""

                if fields_context:
                    print("  [部署器] 使用真实字段名重新生成代码...")
                    try:
                        from generator.generate import generate
                        new_path = generate(req, cfg, fields_map=fields_map)
                        apl_code = new_path.read_text(encoding="utf-8")
                        print("  [部署器] 代码已用真实字段名重新生成 ✓")
                    except Exception as e:
                        print(f"  [部署器] 重新生成失败，使用原始代码: {e}")
        except Exception as e:
            print(f"  [字段抓取] 编辑器内字段抓取异常: {e}")

    # 尝试多种编辑器 API 写入代码（各自 try-catch 独立容错）
    filled = frame.evaluate(f"""
        () => {{
            const text = {repr(apl_code)};

            // 1. CodeMirror
            try {{
                const cmEl = document.querySelector('.CodeMirror');
                if (cmEl && cmEl.CodeMirror) {{
                    cmEl.CodeMirror.setValue(text);
                    return 'codemirror';
                }}
            }} catch(e) {{}}

            // 2. Monaco - getEditors / getModels 两种 API
            try {{
                if (window.monaco && window.monaco.editor) {{
                    const me = window.monaco.editor;
                    // 新版 API
                    if (typeof me.getEditors === 'function') {{
                        const eds = me.getEditors();
                        if (eds.length > 0) {{
                            const model = eds[0].getModel();
                            eds[0].executeEdits('', [{{range: model.getFullModelRange(), text}}]);
                            return 'monaco_editors';
                        }}
                    }}
                    // 旧版 API
                    if (typeof me.getModels === 'function') {{
                        const models = me.getModels();
                        if (models.length > 0) {{
                            models[0].setValue(text);
                            return 'monaco_models';
                        }}
                    }}
                }}
            }} catch(e) {{}}

            // 3. ACE - 多种方式尝试获取编辑器实例
            try {{
                const aceEl = document.querySelector('.ace_editor');
                if (aceEl) {{
                    let editor = null;
                    // 3a. window.ace
                    if (!editor && window.ace && typeof window.ace.edit === 'function') {{
                        try {{ editor = window.ace.edit(aceEl); }} catch(e) {{}}
                    }}
                    // 3b. 全局 ace（不带 window 前缀）
                    if (!editor && typeof ace !== 'undefined' && typeof ace.edit === 'function') {{
                        try {{ editor = ace.edit(aceEl); }} catch(e) {{}}
                    }}
                    // 3c. 元素上缓存的实例（ACE 有时把实例挂在 DOM 元素属性上）
                    if (!editor) {{
                        for (const k of Object.keys(aceEl)) {{
                            if (aceEl[k] && typeof aceEl[k].setValue === 'function') {{
                                editor = aceEl[k]; break;
                            }}
                        }}
                    }}
                    if (editor) {{
                        editor.session.setValue(text);
                        try {{ editor._signal('change', {{}}); }} catch(e) {{}}
                        editor.focus();
                        return 'ace';
                    }}
                    return 'ace_noinst';  // 找到元素但无法获取实例
                }}
            }} catch(e) {{}}

            return 'not_found';
        }}
    """)
    print(f"  [部署器] 代码填写方式: {filled}")

    # JS 注入失败 / ACE 元素存在但无法获取实例 → 键盘粘贴（最可靠）
    if filled in ("not_found", "ace_noinst", "contenteditable"):
        print("  [部署器] 使用键盘粘贴方式填入代码...")
        # 优先点击 ACE editor 区域，否则点击对话框左侧中央
        try:
            ace_loc = frame.locator('.ace_editor').first
            if ace_loc.is_visible(timeout=2000):
                ace_loc.click()
            else:
                raise Exception()
        except Exception:
            frame.mouse.click(360, 350)
        time.sleep(0.5)
        # Ctrl+A 全选，Delete 清空
        frame.keyboard.press("Control+a")
        time.sleep(0.2)
        frame.keyboard.press("Delete")
        time.sleep(0.2)
        # JS 复制代码到系统剪贴板
        frame.evaluate(f"""
            () => {{
                const ta = document.createElement('textarea');
                ta.value = {repr(apl_code)};
                ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }}
        """)
        time.sleep(0.3)
        frame.keyboard.press("Control+v")
        time.sleep(1.5)
        filled = "keyboard_paste"

    time.sleep(0.3)

    # ── 先「保存草稿」，对话框保持开着，后续可运行 ──
    _click_save_draft_btn(frame)
    time.sleep(0.8)
    print("  [部署器] 草稿已保存")

    # 等待数据源下拉就绪（保存后需时间渲染，el-select 异步加载）
    time.sleep(5)

    # ── 选数据源 → 运行 → 自动修复循环（编译错误 + 业务逻辑校验）──
    final_code, compile_err = _run_and_check(
        frame, cfg=cfg, current_code=apl_code,
        output_file=output_file, func_name=func_name, req=req)
    if compile_err:
        raise RuntimeError(
            "APL 运行/编译未通过，已跳过正式发布（此前版本可能仍为草稿）。\n"
            + str(compile_err)[:2000]
        )

    # ── 所有修复完成后，正式发布（点「保存」并等待对话框关闭）──
    _final_publish(frame, cfg=cfg, current_code=final_code or apl_code,
                   output_file=output_file, func_name=func_name)
    print("[部署器] 保存完成（请核查截图确认结果）")


def _get_datasource_input(frame):
    """返回数据源选择器的可点击元素 Locator。单次 JS 调用完成定位，不依赖 Vision Agent。"""
    # 优先：placeholder 含「数据源」「请选择」的 input
    for sel in ['input[placeholder*="数据源"]', 'input[placeholder*="请选择"]', '.el-select input']:
        try:
            loc = frame.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=500):
                return loc
        except Exception:
            continue
    try:
        idx = frame.evaluate("""
            () => {
                const all = [...document.querySelectorAll('.el-input__inner')];
                if (!all.length) return -1;

                function yDist(a, b) {
                    return Math.abs((a.top + a.height / 2) - (b.top + b.height / 2));
                }
                function bestInRow(anchorRect) {
                    let best = -1, dist = 999;
                    all.forEach((inp, i) => {
                        const r = inp.getBoundingClientRect();
                        if (r.height < 18 || r.height > 60) return;
                        const d = yDist(r, anchorRect);
                        if (d < 40 && d < dist) { dist = d; best = i; }
                    });
                    return best;
                }

                // A: placeholder 包含「数据源」「请选择」
                const phIdx = all.findIndex(inp =>
                    ((inp.placeholder || '') + (inp.getAttribute('placeholder') || '')).match(/数据源|请选择/)
                );
                if (phIdx >= 0) return phIdx;

                // B: 用「扫描函数」做锚点
                for (const el of document.querySelectorAll('*')) {
                    if (el.textContent.trim() !== '扫描函数') continue;
                    const r = el.getBoundingClientRect();
                    if (r.height <= 0) continue;
                    const b = bestInRow(r);
                    if (b >= 0) return b;
                }

                // C: 从「运行脚本」向上找 el-select
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
                    acceptNode: n => n.textContent.trim() === '运行脚本'
                        ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP
                });
                let node = walker.nextNode();
                while (node) {
                    let p = node.parentElement;
                    for (let i = 0; i < 6; i++) {
                        if (!p) break;
                        const inp = p.querySelector('.el-select .el-input__inner, .paasf-form-select .el-input__inner');
                        if (inp && inp.getBoundingClientRect().height > 0)
                            return Math.max(0, all.indexOf(inp));
                        p = p.parentElement;
                    }
                    node = walker.nextNode();
                }

                // D: 底部最后一个合适的 input
                for (let i = all.length - 1; i >= 0; i--) {
                    const r = all[i].getBoundingClientRect();
                    if (r.height >= 18 && r.height <= 60 && r.width > 80) return i;
                }

                return -1;
            }
        """)
        if idx >= 0:
            loc = frame.locator('.el-input__inner').nth(idx)
            if loc.count() > idx:
                return loc
    except Exception:
        pass
    return None


def _get_open_datasource_popper(frame, count_before: int = 0) :
    """等待数据源下拉弹出并返回选项列表，结果出现即返回，不轮询。"""
    _READ_JS = """
        () => {
            const poppers = [...document.querySelectorAll(
                '.el-select-dropdown.el-popper, .el-popper, [class*="dropdown"]'
            )];
            const visible = poppers.filter(p => {
                const r = p.getBoundingClientRect();
                return r.height > 30 && r.width > 30 && getComputedStyle(p).display !== 'none';
            });
            for (const target of visible.reverse()) {
                const items = [...target.querySelectorAll(
                    'li.el-select-dropdown__item:not(.is-disabled), li[class*="item"], .el-select-dropdown__item, li'
                )].filter(li => li.textContent.trim() && li.offsetHeight > 0);
                if (items.length > 0) return items.map(li => li.textContent.trim());
            }
            const custom = [...document.querySelectorAll(
                '[class*="paasf"] [class*="option"], [class*="select-option"], [class*="dropdown-item"]'
            )].filter(el => el.textContent.trim() && el.offsetHeight > 0);
            if (custom.length > 0) return custom.map(el => el.textContent.trim());
            return null;
        }
    """
    try:
        frame.wait_for_function(_READ_JS, timeout=3000)
    except Exception:
        return []
    result = frame.evaluate(_READ_JS)
    return result or []


def _open_datasource_dropdown(frame, cfg: dict = None) :
    """点开数据源下拉，返回选项文字列表；展开失败返回空列表。
    先尝试 Playwright 选择器（快速），失败则 fallback 到 agent vision。"""
    inp = _get_datasource_input(frame)
    if not inp:
        # Playwright 找不到输入框，直接走 agent
        if cfg:
            print("  [部署器] Playwright 未找到数据源选择框，尝试 agent vision...")
            return _agent_open_datasource(frame, cfg)
        print("  [部署器] 未找到数据源选择框，将不选数据源运行")
        return []

    count_before = frame.evaluate(
        "() => document.querySelectorAll('.el-select-dropdown.el-popper').length"
    )
    clicked = False
    try:
        inp.click(timeout=3000)
        clicked = True
    except Exception:
        pass
    if not clicked:
        try:
            inp.evaluate("el => { el.focus(); el.click(); el.dispatchEvent(new MouseEvent('click', {bubbles:true})); }")
            clicked = True
        except Exception:
            pass
    if not clicked:
        if cfg:
            print("  [部署器] 数据源输入框点击失败，尝试 agent vision...")
            return _agent_open_datasource(frame, cfg)
        return []

    options = _get_open_datasource_popper(frame, count_before)
    if not options:
        # 再尝试一次：有些 el-select 需要双击或点 suffix icon
        try:
            suffix = frame.locator('.el-input__suffix, .el-select__caret, [class*="arrow"]').first
            if suffix.is_visible(timeout=1000):
                suffix.click(timeout=2000)
                time.sleep(0.6)
                options = _get_open_datasource_popper(frame, count_before)
        except Exception:
            pass

    if not options:
        # Playwright 选择器失败，fallback 到 agent vision（下拉可能仍展开）
        if cfg:
            print("  [部署器] Playwright 选择器未能读到下拉选项，尝试 agent vision...")
            try:
                from deployer.browser_agent import agent_read_datasource_options
                options = agent_read_datasource_options(frame, cfg)
                if options:
                    print(f"  [agent] 成功读到 {len(options)} 个数据源选项: {options[:3]}...")
                    frame.keyboard.press("Escape")
                    return options
            except Exception as e:
                print(f"  [agent] vision 读取失败: {e}")
            # agent 也没读到，再尝试重新点开
            frame.keyboard.press("Escape")
            time.sleep(0.5)
            return _agent_open_datasource(frame, cfg)
        frame.keyboard.press("Escape")
        print("  [部署器] 数据源下拉无选项或加载超时")
    else:
        print(f"  [部署器] 数据源下拉已展开，共 {len(options)} 个选项: {options[:3]}...")
    return options


def _select_datasource_by_idx(frame, idx: int, cfg: dict = None) -> str:
    """展开数据源下拉并点击第 idx 个选项，返回选中文本。
    先试 Playwright（快），失败再用 agent 视觉（慢但不依赖 DOM）。"""
    inp = _get_datasource_input(frame)
    if not inp:
        if cfg:
            try:
                from deployer.browser_agent import agent_select_datasource
                return agent_select_datasource(frame, cfg, idx) or "no_input"
            except Exception as e:
                print(f"  [agent] 数据源选择异常: {e}")
        return "no_input"

    count_before = frame.evaluate(
        "() => document.querySelectorAll('.el-select-dropdown.el-popper').length"
    )
    page = getattr(frame, "page", frame)
    clicked = False
    try:
        bbox = inp.bounding_box(timeout=2000)
        if bbox:
            cx = bbox["x"] + bbox["width"] / 2
            cy = bbox["y"] + bbox["height"] / 2
            page.mouse.click(cx, cy)
            clicked = True
    except Exception:
        pass
    if not clicked:
        try:
            inp.click(timeout=3000)
            clicked = True
        except Exception:
            pass
    if not clicked:
        try:
            inp.evaluate("el => { el.focus(); el.click(); el.dispatchEvent(new MouseEvent('click', {bubbles:true})); }")
            clicked = True
        except Exception:
            pass
    if not clicked:
        if cfg:
            try:
                from deployer.browser_agent import agent_select_datasource
                return agent_select_datasource(frame, cfg, idx) or "click_failed"
            except Exception as e:
                print(f"  [agent] 数据源选择异常: {e}")
        return "click_failed"

    time.sleep(1)
    options = _get_open_datasource_popper(frame, count_before)
    if not options:
        try:
            inp.evaluate("el => { el.closest('.el-select')?.querySelector('.el-input__suffix')?.click(); }")
            time.sleep(0.6)
            options = _get_open_datasource_popper(frame, count_before)
        except Exception:
            pass

    # 键盘 fallback：下拉已展开时，ArrowDown + Enter 选择（popper 可能在 iframe 外导致 evaluate 找不到）
    def _try_keyboard_select():
        try:
            inp.focus()
            time.sleep(0.2)
            for _ in range(idx + 1):
                frame.keyboard.press("ArrowDown")
                time.sleep(0.1)
            frame.keyboard.press("Enter")
            time.sleep(0.4)
            return True
        except Exception:
            return False

    if not options:
        print("  [部署器] 未读到选项，尝试键盘选择（ArrowDown+Enter）...")
        if _try_keyboard_select():
            return "keyboard_selected"
        frame.keyboard.press("Escape")
        if cfg:
            try:
                from deployer.browser_agent import agent_select_datasource
                return agent_select_datasource(frame, cfg, idx) or "no_items"
            except Exception as e:
                print(f"  [agent] 数据源选择异常: {e}")
        return "no_items"

    result = frame.evaluate(f"""
        () => {{
            const poppers = [...document.querySelectorAll('.el-select-dropdown.el-popper, .el-popper, [class*="dropdown"]')];
            const visible = poppers.filter(p => {{
                const r = p.getBoundingClientRect();
                return r.height > 30 && r.width > 30 && getComputedStyle(p).display !== 'none';
            }});
            for (const target of visible.reverse()) {{
                const items = [...target.querySelectorAll(
                    'li.el-select-dropdown__item:not(.is-disabled), li[class*="item"], li'
                )].filter(li => li.textContent.trim() && li.offsetHeight > 0);
                if (items.length === 0) continue;
                const item = items[{idx}] || items[items.length - 1];
                if (!item) return 'no_item';
                item.scrollIntoView({{block:'nearest'}});
                ['mousedown','mouseup','click'].forEach(t =>
                    item.dispatchEvent(new MouseEvent(t, {{bubbles:true, cancelable:true, view:window}}))
                );
                return item.textContent.trim();
            }}
            return 'no_dropdown';
        }}
    """)
    time.sleep(0.3)
    if result in ("no_dropdown", "no_item"):
        print("  [部署器] DOM 点击失败，尝试键盘选择...")
        frame.keyboard.press("Escape")
        time.sleep(0.2)
        inp.click(timeout=2000)
        time.sleep(0.8)
        if _try_keyboard_select():
            return "keyboard_selected"
        frame.keyboard.press("Escape")
    return result


def _agent_open_datasource(frame, cfg: dict) :
    """Agent vision fallback：用 Playwright 点开下拉 → agent vision 读选项列表。"""
    try:
        from deployer.browser_agent import agent_read_datasource_options, agent_find_datasource_dropdown

        # 先尝试 Playwright 点开（如果能找到输入框）
        inp = _get_datasource_input(frame)
        if inp:
            try:
                inp.click(timeout=3000)
                time.sleep(0.8)
            except Exception:
                pass
        else:
            # Playwright 找不到，用 agent vision 找并点击
            loc = agent_find_datasource_dropdown(frame, cfg)
            if loc and loc.get("found"):
                frame.mouse.click(loc["x"], loc["y"])
                time.sleep(0.8)
            else:
                print("  [agent] 未找到数据源下拉框")
                return []

        # 用 agent vision 读取已展开的选项
        options = agent_read_datasource_options(frame, cfg)
        if options:
            print(f"  [agent] 成功读到 {len(options)} 个数据源选项: {options[:3]}...")
        else:
            print("  [agent] 未能读到数据源选项")
        frame.keyboard.press("Escape")
        return options
    except Exception as e:
        print(f"  [agent] 数据源读取异常: {e}")
        return []


def _agent_select_datasource(frame, cfg: dict, idx: int = 0) -> str:
    """Agent vision fallback：Playwright 点开下拉 → agent vision 找到并点击选项。"""
    try:
        from deployer.browser_agent import agent_click_datasource_option, agent_find_datasource_dropdown

        # 先展开下拉
        inp = _get_datasource_input(frame)
        if inp:
            try:
                inp.click(timeout=3000)
                time.sleep(0.8)
            except Exception:
                pass
        else:
            loc = agent_find_datasource_dropdown(frame, cfg)
            if loc and loc.get("found"):
                frame.mouse.click(loc["x"], loc["y"])
                time.sleep(0.8)
            else:
                return "agent_no_input"

        # agent vision 识别并点击选项
        click_info = agent_click_datasource_option(frame, cfg, idx)
        if click_info and click_info.get("found"):
            frame.mouse.click(click_info["x"], click_info["y"])
            selected = click_info.get("text", f"option_{idx}")
            print(f"  [agent] 已选择数据源: {selected}")
            time.sleep(0.5)
            return selected

        frame.keyboard.press("Escape")
        return "agent_failed"
    except Exception as e:
        print(f"  [agent] 数据源选择异常: {e}")
        return "agent_failed"


def _wait_for_run_result(frame, timeout: int = 15) -> bool:
    """等待运行结果出现，结果出现即刻返回，不轮询。"""
    try:
        frame.wait_for_function(
            """() => {
                const t = document.body.innerText || '';
                return t.includes('E-E-') || t.includes('StopWatch')
                    || t.includes('[Static type checking]') || t.includes('编译错误')
                    || t.includes('运行完成') || t.includes('fix error Action');
            }""",
            timeout=timeout * 1000
        )
        return True
    except Exception:
        return False


def _click_run_btn(frame):
    """点「运行脚本」按钮。"""
    frame.evaluate("""
        () => {
            const btn = [...document.querySelectorAll('button, .el-button, span, a')]
                .find(b => b.textContent.trim() === '运行脚本');
            if (btn) btn.click();
        }
    """)


def _extract_run_result(frame) -> tuple:
    """读取页面上的错误文本和运行日志。返回 (errors_text, log_text)。"""
    # ── 1. 读「错误提示」弹窗（找最小匹配元素，避免返回整页内容）──
    errors = frame.evaluate("""
        () => {
            // 按类名精确匹配
            const selectors = [
                '[class*="error-tips"]', '[class*="errorTips"]',
                '[class*="run-error"]', '.el-message-box__content',
                '.paas-run-error', '.compile-error'
            ];
            for (const s of selectors) {
                const el = document.querySelector(s);
                if (el && el.getBoundingClientRect().height > 0)
                    return el.innerText.trim();
            }
            // 找包含关键字的「最小」元素（text 长度最短）
            const candidates = [...document.querySelectorAll('div, p, pre, span')]
                .filter(el => {
                    const t = el.innerText || '';
                    return (t.includes('[Static type checking]') || t.includes('编译错误'))
                        && t.length < 4000;
                });
            if (candidates.length === 0) return '';
            candidates.sort((a, b) => (a.innerText.length) - (b.innerText.length));
            return candidates[0].innerText.trim();
        }
    """)

    # ── 2. 关闭弹窗 ──
    frame.evaluate("""
        () => {
            const btn = [...document.querySelectorAll('button, .el-button, [class*="close"]')]
                .find(b => ['确定','关闭','OK','×','x'].includes(b.textContent.trim()));
            if (btn) btn.click();
        }
    """)
    time.sleep(0.3)

    # ── 3. 读运行日志（执行 ID 通常以 E-E- 开头；找最小包含 StopWatch 的块）──
    log = frame.evaluate("""
        () => {
            // 精确类名
            for (const s of ['.run-log', '[class*="run-log"]', '[class*="runLog"]',
                              '.run-result', '[class*="runResult"]', '.log-content']) {
                const el = document.querySelector(s);
                if (el) return el.innerText.trim();
            }
            // 找最小包含执行 ID (E-E-) 或 StopWatch 的元素
            const candidates = [...document.querySelectorAll('div, pre')]
                .filter(el => {
                    const t = el.innerText || '';
                    return (t.match(/E-E-[a-z0-9]+/) || t.includes('StopWatch'))
                        && t.length < 3000;
                });
            if (candidates.length === 0) return '';
            candidates.sort((a, b) => a.innerText.length - b.innerText.length);
            return candidates[0].innerText.trim();
        }
    """)
    return errors.strip(), log.strip()


_BIZ_COMPLETE_KEYWORDS = [
    "完成", "成功", "已关联", "已创建", "已更新", "已新建", "已同步", "已写入", "已发送",
    "已存在", "跳过", "无需处理", "已处理", "创建成功", "更新成功", "关联成功",
]
_BIZ_TERMINATE_KEYWORDS = [
    "终止", "为空", "不存在", "未找到", "跳过", "忽略", "无需", "无数据", "不处理",
    "数据为空", "字段为空", "入参为空", "查无", "查不到", "未匹配",
]
_BIZ_FAILURE_KEYWORDS = [
    "失败", "错误", "异常", "exception", "error", "fail",
]


def _analyze_business_log(log_text: str) :
    """根据运行日志中的 [业务] 行分析业务是否走到完成分支。
    返回 dict: has_complete, has_termination, has_failure, summary。
    """
    if not log_text:
        return {"has_complete": False, "has_termination": False, "has_failure": False, "summary": "无日志"}

    biz_lines = [ln.strip().lower() for ln in log_text.splitlines() if "[业务]" in ln]
    all_lower = log_text.lower()

    if not biz_lines:
        # 没有 [业务] 标签时，用全文关键词兜底判断
        has_complete = any(k in all_lower for k in ["运行完成", "执行成功", "stopwatch"])
        return {
            "has_complete": has_complete, "has_termination": False, "has_failure": False,
            "summary": "无[业务]日志，运行完成" if has_complete else "无[业务]日志，请自行查看日志"
        }

    has_complete = any(k in ln for ln in biz_lines for k in _BIZ_COMPLETE_KEYWORDS)
    has_termination = any(k in ln for ln in biz_lines for k in _BIZ_TERMINATE_KEYWORDS)
    has_failure = any(k in ln for ln in biz_lines for k in _BIZ_FAILURE_KEYWORDS)

    if has_complete and not has_failure:
        summary = "业务日志显示已走到完成分支 ✓"
    elif has_failure:
        summary = "业务日志存在失败/错误，请检查逻辑或数据"
    elif has_termination:
        summary = "业务提前终止（字段/数据为空等），通常为数据问题"
    else:
        summary = "有[业务]日志但未识别到完成/失败，请结合日志自行判断"

    return {
        "has_complete": has_complete,
        "has_termination": has_termination,
        "has_failure": has_failure,
        "summary": summary,
    }


def _refill_editor(frame, new_code: str):
    """在已打开的代码编辑器中替换全部内容（不保存）。"""
    result = frame.evaluate(f"""
        () => {{
            const text = {repr(new_code)};
            // Monaco
            try {{
                if (window.monaco && window.monaco.editor) {{
                    const me = window.monaco.editor;
                    if (typeof me.getEditors === 'function') {{
                        const eds = me.getEditors();
                        if (eds.length > 0) {{
                            const model = eds[0].getModel();
                            eds[0].executeEdits('', [{{range: model.getFullModelRange(), text}}]);
                            return 'monaco';
                        }}
                    }}
                    if (typeof me.getModels === 'function') {{
                        const models = me.getModels();
                        if (models.length > 0) {{ models[0].setValue(text); return 'monaco_models'; }}
                    }}
                }}
            }} catch(e) {{}}
            // ACE - 多种实例获取方式
            try {{
                const aceEl = document.querySelector('.ace_editor');
                if (aceEl) {{
                    let ed = null;
                    if (window.ace && typeof window.ace.edit === 'function')
                        try {{ ed = window.ace.edit(aceEl); }} catch(e) {{}}
                    if (!ed && typeof ace !== 'undefined' && typeof ace.edit === 'function')
                        try {{ ed = ace.edit(aceEl); }} catch(e) {{}}
                    if (!ed) for (const k of Object.keys(aceEl)) {{
                        if (aceEl[k] && typeof aceEl[k].setValue === 'function')
                            {{ ed = aceEl[k]; break; }}
                    }}
                    if (ed) {{
                        ed.session.setValue(text);
                        try {{ ed._signal('change', {{}}); }} catch(e) {{}}
                        ed.focus();
                        return 'ace';
                    }}
                    return 'ace_noinst';
                }}
            }} catch(e) {{}}
            // CodeMirror
            try {{
                const cmEl = document.querySelector('.CodeMirror');
                if (cmEl && cmEl.CodeMirror) {{ cmEl.CodeMirror.setValue(text); return 'codemirror'; }}
            }} catch(e) {{}}
            return 'not_found';
        }}
    """)
    print(f"  [部署器] 代码重填方式: {result}")

    if result in ("not_found", "ace_noinst"):
        try:
            ace_loc = frame.locator('.ace_editor').first
            if ace_loc.is_visible(timeout=1500):
                ace_loc.click()
            else:
                frame.mouse.click(360, 350)
        except Exception:
            frame.mouse.click(360, 350)
        time.sleep(0.3)
        frame.keyboard.press("Control+a")
        time.sleep(0.2)
        frame.keyboard.press("Delete")
        time.sleep(0.2)
        frame.evaluate(f"""
            () => {{
                const ta = document.createElement('textarea');
                ta.value = {repr(new_code)};
                ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
                document.body.appendChild(ta);
                ta.focus(); ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }}
        """)
        time.sleep(0.3)
        frame.keyboard.press("Control+v")
        time.sleep(1.5)
        result = "keyboard_paste"

    time.sleep(0.5)


def _call_llm_fix_business_logic(code: str, log_text: str, requirement: str, cfg: dict) -> tuple:
    """分析业务日志：判断是数据问题（不改）还是逻辑问题（需修复）。
    返回 (fixed_code, issue_type)：issue_type 为 "DATA_ISSUE" 时 fixed_code 为 None。"""
    try:
        from generator.generate import call_llm
    except ImportError:
        return None, "DATA_ISSUE"

    system = """你是纷享销客 APL 业务逻辑分析专家。

根据运行日志和业务需求，判断问题类型：

**DATA_ISSUE（数据问题，不改代码）**：以下情况视为数据问题
- 入参/字段为空（如「组织机构代码为空」「租户ID为空」）
- 查询不到数据（如「未找到匹配的客户」「查无记录」）
- 数据源本身无符合条件的数据

**LOGIC_ISSUE（逻辑问题，需修复代码）**：以下情况视为逻辑问题
- 代码分支走错、逻辑错误
- 字段取值错误、API 调用方式错误
- 应走到完成分支却走到了终止/失败

输出格式（严格遵守）：
- 若为数据问题：第一行只输出 DATA_ISSUE
- 若为逻辑问题：第一行输出 LOGIC_ISSUE，第二行空行，第三行起输出完整 Groovy 代码（不要 ``` 标记）"""

    user = f"""业务需求：
{requirement[:800]}

运行日志：
{log_text[:1500]}

当前代码：
{code[:4000]}

请判断并按要求格式输出。"""

    try:
        resp = call_llm(system, user, cfg)
        lines = resp.strip().split("\n")
        first = lines[0].strip().upper() if lines else ""
        if "DATA_ISSUE" in first:
            return None, "DATA_ISSUE"
        if "LOGIC_ISSUE" in first:
            # 跳过第一行和空行，取代码部分
            code_lines = []
            started = False
            for ln in lines[1:]:
                if started:
                    code_lines.append(ln)
                elif ln.strip():
                    started = True
                    code_lines.append(ln)
            fc = "\n".join(code_lines).strip()
            if fc and "def " in fc:
                if fc.startswith("```"):
                    fc = "\n".join(fc.split("\n")[1:-1]).strip()
                return fc, "LOGIC_ISSUE"
        return None, "DATA_ISSUE"
    except Exception as e:
        print(f"  [警告] 业务逻辑分析失败: {e}")
        return None, "DATA_ISSUE"


def _extract_error_location(err_text: str) -> tuple[int | None, int | None]:
    """从错误文本提取行号、列号。如 'expecting ':' @ line 66, column 5' -> (66, 5)。"""
    import re as _re
    m = _re.search(r'line\s+(\d+)\s*,\s*column\s+(\d+)', err_text, _re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _get_code_context(code: str, line_num: int, context: int = 5) -> str:
    """获取报错行附近的代码片段，便于 LLM 定位。"""
    lines = code.splitlines()
    if not lines or line_num < 1:
        return ""
    idx = line_num - 1
    start = max(0, idx - context)
    end = min(len(lines), idx + context + 1)
    snippet = []
    for i in range(start, end):
        marker = ">>> " if i == idx else "    "
        snippet.append(f"{marker}{i+1}: {lines[i]}")
    return "\n".join(snippet)


def _apply_rule_based_fix(code: str, err_text: str) :
    """规则化快速修复。已知模式直接替换，无需 LLM。成功返回修复后代码，否则返回 None。"""
    import re as _re
    fixed = code
    changed = False

    if "?[\"" in code or "?['" in code or "expecting ',', found '@'" in err_text:
        before = fixed
        fixed = _re.sub(r'\?\["([^"]+)"\]', r'?.get("\1")', fixed)
        fixed = _re.sub(r"\?\['([^']+)'\]", r"?.get('\1')", fixed)
        if fixed != before:
            changed = True
            print("  [自愈] 规则修复：?[\"key\"] -> ?.get(\"key\")")

    if ("unexpected char" in err_text and "`" in err_text) or "反引号" in err_text:
        if "`" in fixed:
            fixed = fixed.replace("`", "")
            changed = True
            print("  [自愈] 规则修复：移除反引号")

    if "ForStatements are not allowed" in err_text and "for (int " in fixed:
        def _for_to_each(m):
            var, coll, body = m.group(1), m.group(2), m.group(3)
            return f"{coll}.each {{ {var} -> {body} }}"
        before = fixed
        fixed = _re.sub(
            r'for\s*\(\s*int\s+(\w+)\s*=\s*0\s*;\s*\1\s*<\s*(\w+)\.size\(\)\s*;\s*\1\+\+\s*\)\s*\{([^}]+)\}',
            _for_to_each,
            fixed,
            flags=_re.DOTALL
        )
        if fixed != before:
            changed = True
            print("  [自愈] 规则修复：for(int i...) -> .each{ i -> }")

    if "ForStatements are not allowed" in err_text and _re.search(r'for\s*\(', fixed):
        before = fixed
        # for (Type var : collection) { body }
        fixed = _re.sub(
            r'for\s*\(\s*\w[\w<>, ]*\s+(\w+)\s*:\s*([\w.()]+)\s*\)\s*\{(.*?)\n\}',
            lambda m: f"{m.group(2)}.each {{ {m.group(1)} ->{m.group(3)}\n}}",
            fixed,
            flags=_re.DOTALL
        )
        if fixed != before:
            changed = True
            print("  [自愈] 规则修复：for(Type var : coll) -> .each{ var -> }")

    if "toJavaDate" in err_text or "setTime" in err_text or "com.fxiaoke.functions.time.Date" in err_text:
        before = fixed
        def _date_cal_to_ts(m):
            months, var = m.group(1), m.group(2)
            days = int(months) * 30
            return f"long {var} = System.currentTimeMillis() - ({days}L * 24 * 60 * 60 * 1000)"
        fixed = _re.sub(
            r'Date\s+now\s*=\s*new\s+Date\(\)\s*\n\s*Calendar\s+cal\s*=\s*Calendar\.getInstance\(\)\s*\n\s*cal\.setTime\(now\)\s*\n\s*cal\.add\(Calendar\.MONTH,\s*-(\d+)\)\s*\n\s*Date\s+(\w+)\s*=\s*cal\.getTime\(\)',
            _date_cal_to_ts,
            fixed
        )
        if fixed != before:
            fixed = _re.sub(r'(\w+)\.format\s*\(\s*["\']yyyy-MM-dd["\']\s*\)', r'"日期范围"', fixed)
            changed = True
            print("  [自愈] 规则修复：Date/Calendar -> System.currentTimeMillis")

    if "expecting ':', found 'if'" in err_text or "found 'if'" in err_text:
        before = fixed

        def _ternary_if_to_block(m):
            var_decl, cond, inner_cond, inner_body, else_val = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            var_name = _re.search(r'def\s+(\w+)', var_decl)
            v = var_name.group(1) if var_name else "tmp"
            return f"{var_decl} = {else_val.strip()}\nif ({cond.strip()} && {inner_cond}) {{ {v} = {inner_body.strip()} }}"

        fixed = _re.sub(
            r'(def\s+\w+)\s*=\s*([^?]+)\s*\?\s*if\s*\(([^)]+)\)\s*\{\s*([^}]+)\s*\}\s*:\s*([^;\n]+)',
            _ternary_if_to_block,
            fixed
        )
        if fixed != before:
            changed = True
            print("  [自愈] 规则修复：三元内含 if -> if-else 块")

    return fixed if changed else None


def _call_llm_fix(code: str, errors: str, cfg: dict, retry_feedback: str = "",
                  prev_errors: list[str] | None = None) -> str:
    """调用 LLM 根据错误修复 APL 代码。失败返回空字符串。
    会从 memory 检索相似历史修复并注入 prompt，形成数据闭环。
    retry_feedback: 同错误多次时提示 LLM 换策略；prev_errors: 历史错误列表用于判断是否重复。"""
    try:
        from generator.generate import call_llm
    except ImportError:
        return ""
    try:
        from deployer import memory_store
        mem_ctx = memory_store.build_memory_prompt_context(errors)
    except Exception:
        mem_ctx = ""

    system = (
        "你是纷享销客 APL 函数专家。请根据静态类型检查错误修复下方 Groovy APL 代码。\n"
        "\n"
        "## 必须遵守的 API 签名规则\n"
        "\n"
        "### ❌ 废弃写法（绝对不能出现）\n"
        "- Fx.object.create(objectApi, data)                          // 2参数，废弃\n"
        "- Fx.object.create(objectApi, data, CreateAttribute)         // 3参数，签名不匹配\n"
        "- Fx.object.update(objectApi, id, data)                      // 3参数，废弃\n"
        "\n"
        "### ✅ 正确签名\n"
        "// create：必须 4 个参数，第3个是空 Map [:]\n"
        "def (Boolean createErr, Map createResult, String createMsg) = Fx.object.create(\n"
        '    "objectApi", ["field": value] as Map<String, Object>, [:],\n'
        "    CreateAttribute.builder().triggerWorkflow(false).build()\n"
        ")\n"
        "\n"
        "// update：必须 4 个参数，第4个是 UpdateAttribute\n"
        "def (Boolean updateErr, Map updateResult, String updateMsg) = Fx.object.update(\n"
        '    "objectApi", id, ["field": value] as Map<String, Object>,\n'
        "    UpdateAttribute.builder().triggerWorkflow(true).build()\n"
        ")\n"
        "\n"
        "// find：必须传入 SelectAttribute 作为第3个参数\n"
        "def (Boolean err, QueryResult r, String msg) = Fx.object.find(\n"
        '    "objectApi",\n'
        "    FQLAttribute.builder().columns([\"_id\"]).queryTemplate(QueryTemplate.AND([\"f\": QueryOperator.EQ(v)])).build(),\n"
        "    SelectAttribute.builder().build()\n"
        ")\n"
        "\n"
        "## 其他修复规则\n"
        "- FQLAttribute 没有 .limit(n) 方法，分页通过 SelectAttribute 处理\n"
        "- 三元组变量名不要用 _（平台报 warning），用真实变量名\n"
        "- QueryOperator.EQ() 参数类型要和字段类型匹配\n"
        "- **禁止使用 `for` 循环**（平台报 ForStatements are not allowed），遍历一律用 `.each { item -> }` 或 `.each { k, v -> }`\n"
        "\n"
        "## ⚠️ 必须返回完整代码\n"
        "- 你的响应必须是**完整的**修复后代码，从第一行到最后一行，不能截断或省略任何部分\n"
        "- 不能只返回修改的片段，必须包含原代码中所有变量声明、逻辑块\n"
        "\n"
        "## ⚠️ 三元运算符（expecting ':', found 'if'）\n"
        "APL 禁止使用三元运算符 `? :`，平台会报此错误。\n"
        "- ❌ 错误：`def x = cond ? if(a){...} : b` 或 `def x = cond ? valA : valB`\n"
        "- ✅ 正确：一律用 if-else 块，不要用任何 `?:`。\n"
        "  ```\n"
        "  def x = defaultVal\n"
        "  if (cond && a) { x = valA } else if (cond) { x = valB }\n"
        "  ```\n"
        "- 修复时：找到报错行附近的 `?`，将 `a ? b : c` 改为 if-else 块\n"
        "\n"
        "## ⚠️ 未使用变量修复规则（扫描 warning 阻断保存）\n"
        "三元组中每个变量都必须在代码中被引用，否则平台报 warning：\n"
        "- find 的 msg 变量：必须写 `if (findErr) { log.error(\"...\" + findMsg); return }`\n"
        "- create 的 result Map：必须写 `String newId = createResult?[\"_id\"] as String`\n"
        "- update 的 result Map：不需要时加 `else { log.info(\"更新成功\") }` 让逻辑完整\n"
        "  或直接将 updateResult 用于某个字段取值\n"
        "\n"
        "⚠️ 响应格式要求（违反将导致编译失败）：\n"
        "- 只输出 Groovy 代码本身，第一个字符必须是代码字符（`/`、`S`、`d`、`i` 等）\n"
        "- 不能在代码前加任何中文说明、分析、原因描述\n"
        "- 不加 markdown 代码块标记（不加 ``` 围栏）\n"
        "- 不加反引号、不加任何非 Groovy 语法字符"
    )
    if mem_ctx:
        system = system.rstrip() + "\n" + mem_ctx

    line_num, col = _extract_error_location(errors)
    err_context = ""
    if line_num:
        snippet = _get_code_context(code, line_num)
        if snippet:
            err_context = f"\n\n**报错位置（第 {line_num} 行附近）：**\n```\n{snippet}\n```\n"
    retry_hint = f"\n\n⚠️ **重试提示**：{retry_feedback}\n" if retry_feedback else ""
    user = f"APL 代码（需修复）：\n{code}\n\n静态类型检查错误：\n{errors}{err_context}{retry_hint}\n\n请返回修复后的完整 APL 代码："

    try:
        fixed = call_llm(system, user, cfg)
        # ── 去掉 LLM 可能带的代码围栏 ──
        if "```" in fixed:
            lines = fixed.split("\n")
            start = next((i for i, l in enumerate(lines) if l.startswith("```")), 0) + 1
            end = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].startswith("```")), len(lines))
            fixed = "\n".join(lines[start:end])
        # ── 去掉 LLM 在代码前加的中文解释行（会导致 unexpected char 编译错误）──
        # 代码有效起始字符：注释符 /、声明关键字首字母、空行
        import re as _re
        code_start_re = _re.compile(r'^(\s*//|\s*/\*|String |def |import |if |Boolean |Map |List |Integer |Long |void |\s*$)')
        lines = fixed.split("\n")
        for i, ln in enumerate(lines):
            if code_start_re.match(ln):
                fixed = "\n".join(lines[i:])
                break
        return fixed.strip()
    except Exception as e:
        print(f"  [警告] LLM 修复调用失败: {e}")
        return ""


def _click_save_draft_btn(frame):
    """点「保存草稿」按钮（中间保存，对话框保持开着可继续运行）。"""
    page = getattr(frame, 'page', frame)
    btn = frame.locator(':text-is("保存草稿")').first
    try:
        bbox = btn.bounding_box(timeout=5000)
        if bbox:
            page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
            return
    except Exception:
        pass
    try:
        btn.click(force=True, timeout=5000)
    except Exception:
        pass


def _click_save_btn(frame):
    """点「保存」按钮（精确文本匹配，与 _click_save_draft_btn 对称）。
    用 :text-is() 而非 CSS 类选择器，因为该平台按钮不符合标准 el-button 结构。
    """
    page = getattr(frame, 'page', frame)

    # :text-is("保存") 严格匹配，不会匹配"保存草稿"
    btn = frame.locator(':text-is("保存")').last

    try:
        count = frame.locator(':text-is("保存")').count()
        print(f"  [调试] :text-is('保存') 找到 {count} 个元素")
    except Exception:
        count = 0

    # 方案A：获取真实坐标，用 page.mouse.click 硬点
    try:
        bbox = btn.bounding_box(timeout=5000)
        if bbox:
            cx = bbox['x'] + bbox['width'] / 2
            cy = bbox['y'] + bbox['height'] / 2
            print(f"  [调试] 坐标点击 ({cx:.0f}, {cy:.0f})")
            page.mouse.click(cx, cy)
            return
    except Exception as e:
        print(f"  [调试] bounding_box 失败: {e}")

    # 方案B：Playwright force click
    try:
        btn.click(force=True, timeout=5000)
        return
    except Exception as e:
        print(f"  [警告] 「保存」按钮点击失败: {e}")


def _confirm_remark_dialog(frame):
    """确认备注弹窗（优先「确定并关闭」，再试「确定」；用坐标点击穿透 Shadow DOM）。"""
    page = getattr(frame, 'page', frame)
    # 优先尝试「确定并关闭」，再试「确定」「提交」「确认」
    for btn_text in ["确定并关闭", "确定", "提交", "确认", "OK"]:
        try:
            btn = frame.locator(f':text-is("{btn_text}")').last
            bbox = btn.bounding_box(timeout=1500)
            if bbox:
                page.mouse.click(bbox['x'] + bbox['width'] / 2, bbox['y'] + bbox['height'] / 2)
                print(f"  [部署器] 备注弹窗已确认 (按钮: {btn_text})")
                time.sleep(0.8)
                return True
        except Exception:
            continue
    # 兜底：force click
    for btn_text in ["确定并关闭", "确定", "提交"]:
        try:
            btn = frame.locator(f':text-is("{btn_text}")').last
            btn.click(force=True, timeout=1000)
            print(f"  [部署器] 备注弹窗已确认-force (按钮: {btn_text})")
            time.sleep(0.8)
            return True
        except Exception:
            continue
    return False


def _handle_save_remark(frame, remark: str = "1"):
    """点「保存」后处理版本备注弹窗：检测弹窗 → 填写备注 → 点确定。
    全程用 Playwright locator + bounding_box 坐标点击，穿透 Shadow DOM。"""
    page = getattr(frame, 'page', frame)

    # 检测备注弹窗（等最多 3 秒）
    dialog_visible = False
    for title_kw in ["请输入版本备注信息", "备注信息", "版本备注"]:
        try:
            if frame.locator(f':text("{title_kw}")').is_visible(timeout=3000):
                dialog_visible = True
                print(f"  [部署器] 检测到备注弹窗: {title_kw}")
                break
        except Exception:
            continue
    if not dialog_visible:
        return

    # 填写备注 textarea：迭代所有 textarea，找有真实尺寸的那个
    # （代码编辑器隐藏 textarea 的 bounding_box 返回 None，跳过即可）
    filled = False
    try:
        count = frame.locator('textarea').count()
        print(f"  [调试] 页面 textarea 共 {count} 个")
        for idx in range(min(count, 10)):
            try:
                ta = frame.locator('textarea').nth(idx)
                bbox = ta.bounding_box(timeout=500)
                if not bbox or bbox['height'] < 20:
                    continue
                cx = bbox['x'] + bbox['width'] / 2
                cy = bbox['y'] + bbox['height'] / 2
                page.mouse.click(cx, cy)
                time.sleep(0.15)
                page.keyboard.press("Control+a")
                page.keyboard.type(remark)
                time.sleep(0.2)
                filled = True
                print(f"  [部署器] 备注已填写(textarea#{idx}, h={bbox['height']:.0f}): {remark!r}")
                break
            except Exception:
                continue
    except Exception as e:
        print(f"  [调试] 填写备注 textarea 失败: {e}")

    if not filled:
        print("  [调试] 未能填写备注，直接点确定")

    # 点确定按钮
    _confirm_remark_dialog(frame)


def _save_in_editor(frame):
    """在代码编辑器页内点「保存草稿」→ 中间保存，对话框保持开着。"""
    _click_save_draft_btn(frame)
    time.sleep(0.8)
    print("  [部署器] 代码已保存草稿")


def _extract_scan_errors(frame) -> str:
    """从页面底部扫描日志区域提取错误/警告文本（用于诊断保存失败原因）。"""
    try:
        text = frame.locator('.scan-log, .scan-result, [class*="scan"], [class*="error-log"]').all_text_contents()
        if text:
            return "\n".join(t.strip() for t in text if t.strip())
    except Exception:
        pass
    # 兜底：用 Playwright 查找含关键词的可见文本
    try:
        keywords = ["接口已过期", "is not used", "Static type checking", "cannot find"]
        msgs = []
        for kw in keywords:
            try:
                locs = frame.locator(f':text("{kw}")').all()
                for loc in locs:
                    if loc.is_visible():
                        msgs.append(loc.inner_text())
            except Exception:
                pass
        return "\n".join(msgs) if msgs else ""
    except Exception:
        return ""


def _final_publish(frame, cfg: dict = None, current_code: str = "",
                   output_file: str = None, func_name: str = ""):
    """所有修复完成后，点「保存」完成发布并等待对话框关闭。"""
    print("  [部署器] 执行最终发布（点「保存」）...")

    # 先按 Escape 关闭任何浮层
    try:
        frame.keyboard.press("Escape")
        time.sleep(0.5)
    except Exception:
        pass

    # 发布前先尝试读取 API 名（编辑器内通常在此时可见）
    if output_file:
        api_name = _read_func_api_name_from_page(frame)
        if api_name:
            save_func_meta(output_file, {"func_api_name": api_name})
            print(f"  [部署器] 函数 API 名（发布前读取）: {api_name}")

    # 保存草稿让编辑器进入干净状态
    _click_save_draft_btn(frame)
    time.sleep(1)

    _click_save_btn(frame)
    time.sleep(1)

    # 处理备注弹窗
    _handle_save_remark(frame)
    time.sleep(0.8)

    # 等待主对话框关闭（最多 30 秒）
    closed = False
    try:
        frame.wait_for_selector(':text("新建自定义APL函数")', state="hidden", timeout=15000)
        closed = True
        print("  [部署器] 函数已发布，对话框已关闭 ✓")
        _screenshot_frame(frame, "published")
    except Exception:
        _screenshot_frame(frame, "publish_timeout")

    # 发布后再读一次 API 名（作为兜底，此时 UI 可能已更新）
    if output_file and closed:
        api_name_after = _read_func_api_name_from_page(frame)
        if api_name_after:
            save_func_meta(output_file, {"func_api_name": api_name_after})
            print(f"  [部署器] 函数 API 名（发布后确认）: {api_name_after}")

    if not closed:
        scan_errors = _extract_scan_errors(frame)
        if scan_errors:
            print(f"  [警告] 保存被阻断，扫描发现以下错误（需修复后重新部署）：\n{scan_errors}")
        else:
            print("  [警告] 等待对话框关闭超时，请核查截图确认保存状态")


def _has_compile_error_on_page(frame) -> bool:
    """检测页面上是否有编译错误（不读取文字，直接检测标志元素可见性）。"""
    return frame.evaluate("""
        () => {
            // 「APL代码fix error Action」按钮只在编译错误时出现
            const fixBtn = [...document.querySelectorAll('button, .el-button, a, span')]
                .find(b => b.textContent.includes('fix error Action')
                        && b.getBoundingClientRect().height > 0);
            if (fixBtn) return true;
            // 「错误提示」弹窗可见
            const errPopup = [...document.querySelectorAll('div')]
                .find(d => {
                    const t = d.innerText || '';
                    return t.includes('[Static type checking]') && t.length < 3000
                        && d.getBoundingClientRect().height > 0;
                });
            return !!errPopup;
        }
    """)


_DS_FAIL = frozenset(("no_input", "click_failed", "no_items", "no_dropdown", "no_item", "agent_failed", "agent_no_input"))


def _click_datasource_option_at_index(frame, idx: int) -> str:
    """下拉已展开时，直接点击第 idx 个选项，返回选中文本。不触发任何打开/关闭操作。"""
    result = frame.evaluate(f"""
        () => {{
            const poppers = [...document.querySelectorAll('.el-select-dropdown.el-popper, .el-popper, [class*="dropdown"]')];
            const visible = poppers.filter(p => {{
                const r = p.getBoundingClientRect();
                return r.height > 30 && r.width > 30 && getComputedStyle(p).display !== 'none';
            }});
            for (const target of visible.reverse()) {{
                const items = [...target.querySelectorAll(
                    'li.el-select-dropdown__item:not(.is-disabled), li[class*="item"], li'
                )].filter(li => li.textContent.trim() && li.offsetHeight > 0);
                if (items.length === 0) continue;
                const item = items[{idx}] || items[items.length - 1];
                if (!item) return 'no_item';
                item.scrollIntoView({{block:'nearest'}});
                ['mousedown','mouseup','click'].forEach(t =>
                    item.dispatchEvent(new MouseEvent(t, {{bubbles:true, cancelable:true, view:window}}))
                );
                return item.textContent.trim();
            }}
            return 'no_dropdown';
        }}
    """)
    time.sleep(0.3)
    return result


def _resolve_datasource_selection(cfg: dict) -> int | str:
    """从 config 解析数据源选择：datasource_index (0-based) 或 datasource_prefer（按名称匹配如「其他数据源」）。"""
    fx = (cfg or {}).get("fxiaoke") or {}
    prefer = (fx.get("datasource_prefer") or "").strip()
    if prefer:
        return prefer
    idx = fx.get("datasource_index")
    if isinstance(idx, int):
        return idx
    if isinstance(idx, str) and idx.isdigit():
        return int(idx)
    return 0


def _select_datasource_by_preference(frame, cfg: dict) -> str:
    """按 config 选择数据源：datasource_prefer 优先按名称匹配，否则用 datasource_index（默认 0）。"""
    val = _resolve_datasource_selection(cfg or {})
    if isinstance(val, str):
        options = _open_datasource_dropdown(frame, cfg)
        if options:
            for i, opt in enumerate(options):
                if val in str(opt) or str(opt) in val:
                    print(f"  [部署器] 按名称匹配数据源「{val}」，选择第 {i+1} 项: {opt}")
                    return _click_datasource_option_at_index(frame, i)
        print(f"  [部署器] 未匹配到「{val}」，回退到第 1 项")
        return _select_datasource_by_idx(frame, 0, cfg=cfg)
    return _select_datasource_by_idx(frame, val, cfg=cfg)


def _do_one_run(frame, attempt_label: str, select_first_datasource: bool = False,
                cfg: dict = None) -> tuple:
    """执行一次「运行脚本」。
    select_first_datasource: 若 True 且存在数据源，则按 config 选择（datasource_prefer 或 datasource_index）再运行；否则不选。
    返回 (has_compile_error, errors_text, log_text)。"""
    if select_first_datasource:
        selected = _select_datasource_by_preference(frame, cfg) if cfg else _select_datasource_by_idx(frame, 0, cfg=cfg)
        if selected in _DS_FAIL:
            time.sleep(2)
            selected = _select_datasource_by_preference(frame, cfg) if cfg else _select_datasource_by_idx(frame, 0, cfg=cfg)
        if not selected or selected in _DS_FAIL:
            print("  [警告] 数据源选择失败，将不选数据源运行（日志可能显示入参为空）")
        elif selected:
            time.sleep(0.3)
    _click_run_btn(frame)
    print(f"  [部署器] 已点击「运行脚本」，等待执行日志...")
    _wait_for_run_result(frame, timeout=18)
    time.sleep(0.3)

    # 先判断编译错误（在提取文字前，弹窗还在）
    has_compile_err = _has_compile_error_on_page(frame)
    if has_compile_err:
        _screenshot_frame(frame, f"compile_err_{attempt_label}")

    errors, log = _extract_run_result(frame)
    if log:
        print(f"  [部署器] 运行日志:\n{log[:300]}")
        if not has_compile_err:
            analysis = _analyze_business_log(log)
            print(f"  [部署器] 业务日志分析: {analysis['summary']}")
            if (analysis["has_termination"] or analysis["has_failure"]) and not analysis["has_complete"]:
                print("  [提示] 未获取到数据或逻辑未走到完成分支时，请根据入参/步骤日志检查数据源与代码逻辑，不要仅以无报错视为成功")

    return has_compile_err, errors, log


def _add_fix_to_memory(err_text: str, diff: str, fixed_code: str = ""):
    """将本次修复写入 memory，供后续同类错误参考。仅在编译通过后调用。"""
    try:
        from deployer import memory_store
        etype = memory_store.classify_error(err_text)
        # 用 diff 中新增行作为 fix_snippet；无则用 fixed_code
        fix_snippet = "\n".join(
            ln[1:] for ln in (diff or "").splitlines() if ln.startswith("+") and not ln.startswith("+++")
        )[:400] if diff else ""
        if not fix_snippet and fixed_code:
            fix_snippet = fixed_code[:400]
        if fix_snippet:
            memory_store.add_fix_memory(etype, err_text[:300], fix_snippet)
    except Exception as e:
        print(f"  [警告] 写入 memory 失败: {e}")


def _write_fix_report(func_name: str, fix_history: list):
    """将修复历史写成 Markdown 报告，保存到 reports/ 目录。"""
    import difflib
    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    ts = int(time.time())
    report_path = reports_dir / f"fix_{func_name[:20]}_{ts}.md"

    lines = [f"# APL 修复报告：{func_name}\n\n",
             f"生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
             f"共修复 {len(fix_history)} 次\n\n"]

    for i, entry in enumerate(fix_history, 1):
        lines.append(f"## 第 {i} 次修复\n\n")
        lines.append(f"**错误信息：**\n```\n{entry['error'][:600]}\n```\n\n")
        if entry.get("diff"):
            lines.append(f"**代码变更（unified diff）：**\n```diff\n{entry['diff']}\n```\n\n")

    report_path.write_text("".join(lines), encoding="utf-8")
    print(f"  [部署器] 修复报告已生成: {report_path}")


def _run_and_check(frame, cfg: dict = None, current_code: str = "",
                   output_file: str = None, func_name: str = "", req: dict = None) -> tuple:
    """主运行循环（自愈式）：带数据源运行 → 编译错误则先规则修复、再 LLM 修复 → 重跑验证 → 重复直到通过。
    1. 规则修复：?[\"key\"]、反引号、for 循环等已知模式直接替换
    2. LLM 修复：注入报错行上下文、历史类似修复、同错误重试时提示换策略
    3. 每次修复后自动重跑验证，形成自愈闭环
    返回 (final_code, last_errors)。"""
    import difflib
    code = current_code
    fix_history: list = []
    attempt = 0
    MAX_FIX = 5
    requirement = (req or {}).get("requirement", "") or ""

    prev_err_sigs: list[str] = []
    compile_passed = False
    last_compile_err = ""

    while attempt <= MAX_FIX:
        has_err, errors, log = _do_one_run(frame, f"r{attempt}", select_first_datasource=True, cfg=cfg)

        if not has_err:
            print("  [部署器] 编译通过 ✓")
            # 复用本次日志做业务分析，避免重复运行
            if log and cfg and requirement:
                analysis = _analyze_business_log(log)
                print(f"  [部署器] 业务分析: {analysis['summary']}")
                if (analysis["has_termination"] or analysis["has_failure"]) and not analysis["has_complete"]:
                    fixed, issue_type = _call_llm_fix_business_logic(code, log, requirement, cfg)
                    if issue_type == "LOGIC_ISSUE" and fixed:
                        print("  [部署器] 逻辑问题，修复后重试...")
                        diff = "".join(difflib.unified_diff(
                            code.splitlines(keepends=True), fixed.splitlines(keepends=True),
                            fromfile=f"v{attempt}", tofile=f"v{attempt+1}", n=2
                        ))
                        fix_history.append({"error": log[:400], "diff": diff})
                        _refill_editor(frame, fixed)
                        _save_in_editor(frame)
                        code = fixed
                        attempt += 1
                        continue
                    else:
                        # 数据问题：切换数据源再跑一次验证
                        options = _open_datasource_dropdown(frame, cfg)
                        if options and len(options) > 1:
                            for ds_idx in range(1, min(len(options), 3)):
                                print(f"  [部署器] 切换数据源（第 {ds_idx+1} 项）再验证...")
                                _click_datasource_option_at_index(frame, ds_idx)
                                time.sleep(0.3)
                                _click_run_btn(frame)
                                _wait_for_run_result(frame, timeout=18)
                                time.sleep(0.3)
                                has_err2, _, log2 = _do_one_run(frame, f"r{attempt}_ds{ds_idx}", select_first_datasource=False, cfg=cfg)
                                if has_err2:
                                    break
                                analysis2 = _analyze_business_log(log2)
                                print(f"  [部署器] 数据源{ds_idx+1}业务分析: {analysis2['summary']}")
                                if analysis2["has_complete"] or not (analysis2["has_termination"] or analysis2["has_failure"]):
                                    print("  [部署器] 切换数据源后验证通过 ✓")
                                    break
                        else:
                            print("  [部署器] 无其他数据源可切换，视为数据问题，代码无需修改")
            compile_passed = True
            break

        attempt += 1
        err_text = errors or log
        last_compile_err = err_text or last_compile_err
        print(f"  [部署器] 编译错误（第 {attempt} 次）:\n{err_text[:400]}")

        if not cfg or not code:
            return code, err_text

        rule_fixed = _apply_rule_based_fix(code, err_text)
        if rule_fixed:
            diff = "".join(
                ln + "\n" for ln in difflib.unified_diff(
                    code.splitlines(keepends=True), rule_fixed.splitlines(keepends=True),
                    fromfile="before", tofile="after", n=2
                )
            )
            fix_history.append({"error": err_text[:600], "diff": diff or "[规则修复]", "fixed_code": rule_fixed})
            code = rule_fixed
            _refill_editor(frame, code)
            _save_in_editor(frame)
            continue

        err_sig = (err_text or "")[:150].replace(" ", "")
        same_count = sum(1 for s in prev_err_sigs if s == err_sig)
        prev_err_sigs.append(err_sig)
        retry_feedback = ""
        if same_count >= 1:
            retry_feedback = f"该错误已修复失败 {same_count + 1} 次，请务必尝试完全不同的修复方式，不要重复上次的修改。"

        print(f"  [部署器] LLM 修复中...")
        fixed = _call_llm_fix(code, err_text, cfg, retry_feedback=retry_feedback)
        if not fixed:
            print("  [警告] LLM 未返回修复结果，终止")
            return code, err_text

        diff = "".join(difflib.unified_diff(
            code.splitlines(keepends=True), fixed.splitlines(keepends=True),
            fromfile=f"v{attempt-1}", tofile=f"v{attempt}", n=2
        ))
        fix_history.append({"error": err_text[:600], "diff": diff, "fixed_code": fixed})
        _refill_editor(frame, fixed)
        _save_in_editor(frame)
        code = fixed

    if fix_history:
        _write_fix_report(func_name or "unknown", fix_history)
        for entry in fix_history:
            _add_fix_to_memory(entry["error"], entry.get("diff", ""), entry.get("fixed_code", ""))

    if output_file and code:
        Path(output_file).write_text(code, encoding="utf-8")
        print(f"  [部署器] 最终代码已回写: {output_file}")

    if not compile_passed:
        msg = (last_compile_err or "").strip() or "编译/运行未通过（已达最大自动修复次数）"
        return code, msg

    return code, ""


# ── 函数元数据（系统生成的 API 名）持久化 ────────────────────────────────────

def _meta_path(apl_file: str) -> Path:
    return Path(apl_file).with_suffix(".meta.yml")


def load_func_meta(apl_file: str) :
    """读取本地保存的函数元数据，不存在返回 {}。"""
    p = _meta_path(apl_file)
    if not p.exists():
        return {}
    try:
        import yaml as _yaml
        return _yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def save_func_meta(apl_file: str, data: dict):
    """将函数元数据写入 .meta.yml（与 APL 文件同目录）。"""
    import yaml as _yaml
    p = _meta_path(apl_file)
    existing = load_func_meta(apl_file)
    existing.update(data)
    p.write_text(_yaml.dump(existing, allow_unicode=True), encoding="utf-8")


def _read_func_api_name_from_page(frame) -> str:
    """从已打开的 APL 编辑器中读取系统生成的函数 API 名（如 Proc_BXYcW__c）。"""
    try:
        result = frame.evaluate(r"""
            () => {
                const text = document.body.innerText;

                // 1. 编辑器头部 "void Proc_XXXXX__c (" 风格
                let m = text.match(/void\s+(\w+__c)\s*\(/);
                if (m) return m[1];

                // 2. 直接出现 Proc_XXXX__c 形式（UI 标签、只读输入框等）
                m = text.match(/\b(Proc_[A-Za-z0-9]+__c)\b/);
                if (m) return m[1];

                // 3. 其他常见 APL 函数前缀
                m = text.match(/\b([A-Z][A-Za-z0-9]*_[A-Za-z0-9]+__c)\b/);
                if (m) return m[1];

                // 4. 查 input/span/label 显示 API 名的元素
                const els = document.querySelectorAll(
                    'input[readonly], input[disabled], .api-name, [class*="apiName"], [class*="api_name"]'
                );
                for (const el of els) {
                    const v = (el.value || el.textContent || '').trim();
                    if (/__c$/.test(v)) return v;
                }

                return '';
            }
        """)
        return result or ""
    except Exception:
        return ""


def find_function_by_api_name(frame, func_api_name: str) -> bool:
    """在函数列表中按系统 API 名搜索，返回是否存在。"""
    try:
        search_loc = _get_search_input_locator(frame)
        if not search_loc:
            return False
        search_loc.fill("")
        search_loc.fill(func_api_name)
        frame.keyboard.press("Enter")
        time.sleep(1.5)
        items = frame.query_selector_all(sel.FUNC_LIST_ITEM)
        for item in items:
            if func_api_name in (item.inner_text() or ""):
                return True
        return False
    except Exception:
        return False


def _deploy_in_page(page, apl_file: str, func_name: str, cfg: dict,
                    namespace: str = "公共库", object_label: str = "",
                    description: str = "", update: bool = False,
                    req: dict = None, ensure_login: bool = True,
                    func_api_name_override: str = "") -> bool:
    """在已有 page 上执行完整部署流程（不打开/关闭浏览器）。
    ensure_login=True 时检查 session 是否有效并在必要时重新登录；
    ensure_login=False 时跳过登录检查（调用方已保证已登录）。
    返回是否成功。
    """
    code = Path(apl_file).read_text(encoding="utf-8")
    meta = load_func_meta(apl_file)
    # func_api_name：CLI 覆盖 > meta > req（更新模式时用户可指定要修改的 API 名）
    func_api_name = (
        func_api_name_override.strip()
        or (meta.get("func_api_name") or "").strip()
        or ((req or {}).get("func_api_name") or "").strip()
    )

    login_path = cfg["fxiaoke"].get("login_path", "/XV/UI/login")

    def _is_login_page() -> bool:
        """检测当前页面是否为登录页（URL 判断 + 登录 UI 元素判断双重保险）。"""
        if login_path in page.url:
            return True
        if "proj/page/login" in page.url or "/page/login" in page.url:
            return True
        # SPA hash 路由可能 URL 不变但内嵌了登录 UI（如 /XV/UI/manage#login）
        try:
            loc = page.locator(':text("扫码登录"), :text("账号登录"), :text("动态验证码登录")')
            if loc.first.is_visible(timeout=1500):
                return True
        except Exception:
            pass
        return False

    def _go_to_func_list() -> bool:
        """导航到函数列表，等待「新建APL函数」出现（最多 20s）。
        若被重定向到登录页则返回 False，否则返回 True。"""
        navigate_to_function_list(page, cfg)
        cur_url = page.url
        print(f"  [部署器] 当前URL: {cur_url}")
        if _is_login_page():
            return False  # session 失效，被踢到登录页
        # 等函数列表核心元素出现（hash SPA 路由渲染较慢，给足 20s）
        frame_inner = get_frame(page)
        if frame_inner.locator(':text("新建APL函数")').count() > 0:
            return True
        # 最后尝试：再等 8s
        try:
            page.wait_for_selector(':text("新建APL函数")', timeout=8000)
            return True
        except Exception:
            pass
        if _is_login_page():
            return False
        # 还没出来，可能还在主 app 渲染中，二次导航一次
        navigate_to_function_list(page, cfg)
        try:
            page.wait_for_selector(':text("新建APL函数")', timeout=10000)
            return True
        except Exception:
            pass
        if _is_login_page():
            return False
        screenshot(page, "wrong_page")
        raise RuntimeError(
            f"导航到函数列表失败（URL: {page.url}）。\n"
            "可能原因：\n"
            "  1. config.fxiaoke.function_path 配置有误\n"
            "  2. 该账号无函数管理权限\n"
            "  3. SPA 路由加载异常，可尝试有头模式排查（去掉 --headless）"
        )

    if ensure_login:
        has_session = False
        from deployer.deploy_login import get_session_path
        if get_session_path(cfg).exists():
            has_session = load_cookies(page.context, cfg)
            if has_session:
                time.sleep(2)
                ok = _go_to_func_list()
                if not ok:
                    print("  [部署器] Session 已过期，尝试 token 登录...")
                    has_session = False
        if not has_session:
            bootstrap_url = (cfg.get("fxiaoke") or {}).get("bootstrap_token_url", "").strip() or None
            if not bootstrap_url:
                bootstrap_url = __import__("os").environ.get("FX_BOOTSTRAP_TOKEN_URL", "").strip() or None
            if bootstrap_url:
                print(f"  [部署器] 使用 token URL 登录...")
                page.goto(bootstrap_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(4)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                if login_path not in page.url and "proj/page/login" not in page.url:
                    save_cookies(page.context, cfg)
                    has_session = True
                    ok = _go_to_func_list()
                    if ok:
                        has_session = True
                    else:
                        has_session = False
                else:
                    has_session = False
        if not has_session:
            has_session = load_cookies(page.context, cfg)
            if has_session:
                time.sleep(2.5)
                ok = _go_to_func_list()
                if not ok:
                    print("  [部署器] Session 已过期，重新登录...")
                    has_session = False
        if not has_session:
            agent_id = (cfg.get("fxiaoke") or {}).get("agent_login_employee_id", "").strip()
            if not agent_id:
                agent_id = (cfg.get("openapi") or {}).get("current_open_user_id", "1000")
            if agent_id:
                try:
                    from deployer.agent_login import login_via_agent, get_session_cookies
                    cookies = get_session_cookies(cfg) or page.context.cookies()
                    if cookies and login_via_agent(page, cfg, cookies) and _go_to_func_list():
                        save_cookies(page.context, cfg)
                        has_session = True
                except Exception as e:
                    print(f"  [部署器] 代理登录失败: {e}，将转为手动登录")
            if not has_session:
                if not wait_for_manual_login(page, cfg):
                    raise RuntimeError("等待手动登录超时，请重试。")
                save_cookies(page.context, cfg)
                time.sleep(2)
                if not _go_to_func_list():
                    screenshot(page, "login_then_redirect")
                    raise RuntimeError("登录后仍被重定向到登录页，请检查账号权限或手动登录后重试。")
    else:
        _go_to_func_list()

    frame = get_frame(page)

    screenshot(page, "step_func_list")

    kwargs = dict(cfg=cfg, output_file=apl_file, req=req)

    # ── 部署模式（两路径，不混用）──
    # 【新建函数】用户说「生成函数」「函数需求」时：不搜索，直接新建。pipeline 默认即此路径。
    # 【更新函数】用户说「需求变更」「需求修改」且提供了系统函数 API 名时：按 API 名搜索 → 点编辑 →
    #   在现有函数基础上修改。使用 --update 且 func_api_name（来自 req.yml / .meta.yml / --func-api-name）。
    if update:
        # 【更新模式】需求变更/需求修改：必须提供 func_api_name，按 API 名搜索后点编辑，在现有函数基础上修改
        if not func_api_name:
            func_api_name = (req or {}).get("func_api_name", "").strip()
        if not func_api_name:
            raise RuntimeError(
                "更新模式需提供函数 API 名（func_api_name）。"
                "在 req.yml 中填写 func_api_name: Proc_XXX__c，或使用 --func-api-name Proc_XXX__c"
            )
        exists = find_function_by_api_name(frame, func_api_name)
        print(f"  [部署器] 需求变更/修改模式：按 API 名 [{func_api_name}] 搜索 → {'找到，进入编辑' if exists else '未找到'}")
        if not exists:
            raise RuntimeError(f"未找到 API 名为 [{func_api_name}] 的函数，无法更新。请确认 API 名正确。")
        try:
            update_function(frame, func_name, code, **kwargs)
        except RuntimeError as e:
            raise RuntimeError(f"更新失败: {e}")
    else:
        # 【新建模式】函数需求：不搜索，直接新建
        obj_label = object_label or (req or {}).get("object_label", "")
        if not obj_label and namespace in ("流程", "工作流"):
            obj_label = _parse_binding_object_from_apl(apl_file)
            if obj_label:
                print(f"  [部署器] 从 APL 解析绑定对象: {obj_label}")
        print(f"  [部署器] 新建函数：直接创建（不搜索）")
        create_function(frame, func_name, code, namespace=namespace,
                        object_label=obj_label, description=description,
                        **kwargs)

    save_cookies(page.context, cfg)
    print(f"[部署器] 部署完成: {func_name}")
    return True


def _is_target_closed_error(e: Exception) -> bool:
    """判断是否为浏览器/页面已关闭类错误。"""
    name = type(e).__name__
    msg = str(e).lower()
    return "TargetClosed" in name or "target" in msg and "closed" in msg


def deploy(apl_file: str, func_name: str, cfg: dict, headless: bool = False,
           namespace: str = "公共库", object_label: str = "", description: str = "",
           update: bool = False, req: dict = None, func_api_name: str = "") -> bool:
    """主部署流程，返回是否成功。

    部署模式：
      【新建函数】默认：不搜索，直接新建。适用于「生成函数」「函数需求」。
      【更新函数】--update：需求变更/需求修改时，必须提供 func_api_name，按 API 名搜索 → 点编辑 → 在现有函数基础上修改。

    纯证书模式：配置 ShareDev 证书且为更新模式时，直接通过 API 推送，无需浏览器/登录。
    """
    api_name = func_api_name or ((req or {}).get("func_api_name") or "").strip()
    if not api_name and Path(apl_file).exists():
        meta_path = Path(apl_file).with_suffix(".meta.yml")
        if meta_path.exists():
            try:
                import yaml
                meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                api_name = (meta.get("func_api_name") or "").strip()
            except Exception:
                pass
    if update and api_name and Path(apl_file).exists():
        try:
            from fetcher.sharedev_client import ShareDevClient, load_sharedev_config
            project = (cfg.get("fxiaoke") or {}).get("project_name", "").strip() or None
            domain, cert = load_sharedev_config(project_name=project)
            body = Path(apl_file).read_text(encoding="utf-8")
            client = ShareDevClient(domain, cert)
            client.update_func_body(api_name, body)
            print(f"[部署器] 纯证书模式：已通过 ShareDev API 更新 [{api_name}]，无需登录")
            return True
        except ValueError:
            pass
        except Exception as e:
            print(f"[部署器] 证书推送失败: {e}，回退到浏览器部署")

    from playwright.sync_api import sync_playwright

    for attempt in range(2):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=headless,
                    slow_mo=100 if headless else 0,
                    args=["--disable-dev-shm-usage", "--no-sandbox"] if headless else []
                )
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()

                try:
                    return _deploy_in_page(page, apl_file, func_name, cfg,
                                           namespace=namespace, object_label=object_label,
                                           description=description, update=update, req=req,
                                           ensure_login=True, func_api_name_override=func_api_name)
                except Exception as e:
                    err_msg = str(e).lower()
                    if _is_target_closed_error(e) and attempt == 0:
                        print("[部署器] 浏览器/页面意外关闭，重试...")
                        continue
                    if attempt == 0 and ("登录" in err_msg or "login" in err_msg):
                        print("[部署器] 首次登录/跳转失败，重试一次...")
                        continue
                    import traceback
                    print(f"[部署器] 部署失败: {e}")
                    traceback.print_exc()
                    try:
                        screenshot(page, "error")
                    except Exception:
                        pass
                    return False
                finally:
                    try:
                        browser.close()
                    except Exception:
                        pass
        except Exception as e:
            if _is_target_closed_error(e) and attempt == 0:
                print("[部署器] 首次启动失败，重试...")
                continue
            raise
    return False


def main():
    parser = argparse.ArgumentParser(description="APL 函数部署器")
    parser.add_argument("--file", required=True, help="APL 文件路径")
    parser.add_argument("--func-name", dest="func_name", required=True, help="纷享销客中的函数名称")
    parser.add_argument("--headless", action="store_true", help="无头模式运行（不显示浏览器）")
    parser.add_argument("--update", action="store_true",
                        help="需求变更/修改模式：按 func_api_name 搜索后编辑，在现有函数基础上修改")
    parser.add_argument("--func-api-name", dest="func_api_name", default="",
                        help="更新模式时必填：系统函数 API 名，如 Proc_XXX__c")
    parser.add_argument("--config", default=None, help="config 文件路径")
    args = parser.parse_args()

    cfg = load_config(args.config)
    ok = deploy(args.file, args.func_name, cfg,
                headless=args.headless, update=args.update,
                func_api_name=getattr(args, "func_api_name", "") or "")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
