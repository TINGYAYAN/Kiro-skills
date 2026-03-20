"""
轻量级 Browser Agent：用 LLM Vision + Playwright 截图实现智能页面交互。

不依赖 browser-use 库（需要 Python 3.11+），仅用 openai SDK + playwright。
核心思路：截图 → LLM 识别元素位置 → Playwright 点击坐标。

用于替代硬编码 CSS 选择器的脆弱逻辑（如数据源下拉选择）。
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Optional

_SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"


def _take_screenshot_b64(page_or_frame, label: str = "agent") -> str:
    """截图并返回 base64 编码的 PNG 字符串。"""
    _SCREENSHOTS_DIR.mkdir(exist_ok=True)
    path = _SCREENSHOTS_DIR / f"agent_{label}_{int(time.time())}.png"
    try:
        buf = page_or_frame.screenshot(type="png")
        path.write_bytes(buf)
        return base64.b64encode(buf).decode("utf-8")
    except Exception as e:
        print(f"  [agent] 截图失败: {e}")
        return ""


def _call_vision(cfg: dict, system: str, user_text: str, image_b64: str,
                 model: str = None) -> str:
    """调用支持 vision 的 LLM，返回文本响应。"""
    from openai import OpenAI

    llm_cfg = cfg.get("llm", {})
    client = OpenAI(
        base_url=llm_cfg.get("base_url", "https://www.deepclaw.one/v1"),
        api_key=llm_cfg.get("api_key", ""),
        timeout=llm_cfg.get("timeout", 60),
    )
    model = model or "claude-sonnet-4-6"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text", "text": user_text},
            {"type": "image_url", "image_url": {
                "url": f"data:image/png;base64,{image_b64}"
            }},
        ]},
    ]

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
        temperature=0,
    )
    return (resp.choices[0].message.content or "").strip()


# ---------------------------------------------------------------------------
# 数据源选择 Agent
# ---------------------------------------------------------------------------

_DS_SYSTEM = (
    "你是一个浏览器自动化助手。用户会给你一个网页截图，你需要根据指令分析页面并返回 JSON。\n"
    "所有坐标都是相对于截图左上角的像素坐标。\n"
    "只输出 JSON，不加任何解释。"
)


def agent_find_datasource_dropdown(page_or_frame, cfg: dict) -> Optional[dict]:
    """用 LLM vision 在截图中找到「数据源」下拉选择框的位置。
    返回 {"x": int, "y": int, "found": True} 或 {"found": False}。
    """
    img = _take_screenshot_b64(page_or_frame, "ds_find")
    if not img:
        return {"found": False}

    prompt = (
        '在这个截图中，找到"数据源"下拉选择框。'
        '特征：在"运行脚本"按钮同一行或附近，有"请选择数据源"或空白输入框，'
        '可能是 el-select 样式（带下拉箭头）。点击它的中心可展开下拉。\n'
        '返回：{"found": true, "x": 中心X像素, "y": 中心Y像素} 或 {"found": false}\n'
        '只输出 JSON。'
    )
    try:
        resp = _call_vision(cfg, _DS_SYSTEM, prompt, img)
        return _parse_json(resp)
    except Exception as e:
        print(f"  [agent] 查找数据源下拉失败: {e}")
        return {"found": False}


def agent_read_datasource_options(page_or_frame, cfg: dict) -> list:
    """截图后让 LLM 读取当前已展开的下拉选项列表。
    返回 ["选项1", "选项2", ...] 或空列表。
    """
    img = _take_screenshot_b64(page_or_frame, "ds_options")
    if not img:
        return []

    prompt = (
        '截图中有一个已经展开的下拉菜单（数据源选项列表）。\n'
        '请读取所有可见的选项文本，按从上到下的顺序返回 JSON 数组。\n'
        '如果没有看到展开的下拉菜单或没有选项，返回空数组 []。\n'
        '只输出 JSON 数组，例如：["E-E.gjldkj2025.1001-12345", "E-E.gjldkj2025.1001-67890"]'
    )
    try:
        resp = _call_vision(cfg, _DS_SYSTEM, prompt, img)
        result = _parse_json(resp)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"  [agent] 读取数据源选项失败: {e}")
        return []


def agent_click_datasource_option(page_or_frame, cfg: dict, option_idx: int = 0) -> Optional[dict]:
    """截图后让 LLM 找到已展开下拉菜单中第 N 个选项的坐标并返回。
    返回 {"x": int, "y": int, "text": "选项文本", "found": True} 或 {"found": False}。
    """
    img = _take_screenshot_b64(page_or_frame, f"ds_click_{option_idx}")
    if not img:
        return {"found": False}

    ordinal = "第一个" if option_idx == 0 else f"第{option_idx + 1}个"
    prompt = (
        f'截图中有一个已展开的下拉菜单。请找到{ordinal}选项的中心坐标。\n'
        '返回 JSON：{"found": true, "x": 像素X, "y": 像素Y, "text": "选项文本内容"}\n'
        '如果看不到展开的下拉菜单，返回：{"found": false}\n'
        '只输出 JSON。'
    )
    try:
        resp = _call_vision(cfg, _DS_SYSTEM, prompt, img)
        return _parse_json(resp)
    except Exception as e:
        print(f"  [agent] 点击数据源选项失败: {e}")
        return {"found": False}


def agent_find_run_button(page_or_frame, cfg: dict) -> Optional[dict]:
    """用 LLM vision 找到「运行脚本」按钮的坐标。"""
    img = _take_screenshot_b64(page_or_frame, "run_btn")
    if not img:
        return {"found": False}

    prompt = (
        '在截图中找到"运行脚本"按钮（通常是蓝色按钮，文字为"运行脚本"）。\n'
        '返回它的中心坐标：{"found": true, "x": 像素X, "y": 像素Y}\n'
        '如果找不到，返回：{"found": false}\n'
        '只输出 JSON。'
    )
    try:
        resp = _call_vision(cfg, _DS_SYSTEM, prompt, img)
        return _parse_json(resp)
    except Exception as e:
        print(f"  [agent] 查找运行脚本按钮失败: {e}")
        return {"found": False}


# ---------------------------------------------------------------------------
# 高级 API：完整的数据源选择流程
# ---------------------------------------------------------------------------

def agent_select_datasource(page_or_frame, cfg: dict, option_idx: int = 0) -> str:
    """完整流程：找到数据源下拉 → 点开 → 选择第 N 个选项。
    返回选中的选项文本，失败返回空字符串。
    """
    print("  [agent] 开始智能数据源选择...")

    # Step 1: 找到数据源下拉框
    loc = agent_find_datasource_dropdown(page_or_frame, cfg)
    if not loc or not loc.get("found"):
        print("  [agent] 未找到数据源下拉框")
        return ""

    print(f"  [agent] 找到数据源下拉: ({loc['x']}, {loc['y']})")

    # Step 2: 点击展开下拉（可能需多次点击）
    for attempt in range(2):
        page_or_frame.mouse.click(loc["x"], loc["y"])
        time.sleep(1.2)

        # Step 3: 读取选项列表
        options = agent_read_datasource_options(page_or_frame, cfg)
        if options:
            break
        if attempt == 0:
            print("  [agent] 下拉未展开，再点一次")
            page_or_frame.keyboard.press("Escape")
            time.sleep(0.3)

    if not options:
        print("  [agent] 数据源无选项")
        page_or_frame.keyboard.press("Escape")
        return ""

    print(f"  [agent] 读到 {len(options)} 个数据源选项: {options[:3]}...")

    # Step 4: 点击目标选项
    target_idx = min(option_idx, len(options) - 1)
    click_info = agent_click_datasource_option(page_or_frame, cfg, target_idx)
    if click_info and click_info.get("found"):
        page_or_frame.mouse.click(click_info["x"], click_info["y"])
        selected = click_info.get("text", options[target_idx] if target_idx < len(options) else "")
        print(f"  [agent] 已选择数据源: {selected}")
        time.sleep(0.3)
        return selected

    # Fallback: 直接用 Playwright 按文字点击
    if target_idx < len(options):
        text = options[target_idx]
        try:
            page_or_frame.locator(f'li:has-text("{text}")').first.click(timeout=3000)
            print(f"  [agent] 已选择数据源(fallback): {text}")
            return text
        except Exception:
            pass

    page_or_frame.keyboard.press("Escape")
    return ""


def agent_open_datasource_dropdown(page_or_frame, cfg: dict) -> list:
    """找到数据源下拉 → 点开 → 返回选项列表（不选择）。"""
    loc = agent_find_datasource_dropdown(page_or_frame, cfg)
    if not loc or not loc.get("found"):
        return []

    page_or_frame.mouse.click(loc["x"], loc["y"])
    time.sleep(0.8)

    options = agent_read_datasource_options(page_or_frame, cfg)
    if not options:
        page_or_frame.mouse.click(loc["x"], loc["y"])
        time.sleep(1)
        options = agent_read_datasource_options(page_or_frame, cfg)

    page_or_frame.keyboard.press("Escape")
    return options


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------

def _parse_json(text: str):
    """从 LLM 响应中提取 JSON（兼容 markdown fence 包裹）。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i in range(1, len(lines)):
            if lines[i].strip().startswith("```"):
                end = i
                break
        text = "\n".join(lines[start:end]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找第一个 { 或 [
        for i, ch in enumerate(text):
            if ch in ("{", "["):
                try:
                    return json.loads(text[i:])
                except json.JSONDecodeError:
                    continue
        return {}
