"""
APL 报错修复记忆（Memory）

- 分类记录每次修复：错误类型、错误片段、修复方式
- 遇到类似错误时，从记忆检索并注入 prompt，形成数据闭环
- 持续积累后，同类问题可直接参考历史修复
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

MEMORY_DIR = Path(__file__).parent / "memory"
MEMORY_FILE = MEMORY_DIR / "fix_memory.json"

# 错误类型分类规则（关键词 → 类型）
ERROR_TYPE_RULES = [
    (r"is not used|未使用变量|variable.*not used", "未使用变量"),
    (r"expecting ':', found 'if'|found 'if'", "三元内含if"),
    (r"expecting ':'|Elvis|\\?:", "Elvis运算符"),
    (r"CreateAttribute|UpdateAttribute|SelectAttribute|签名|signature|build\(\)", "API签名"),
    (r"\?\[|expecting ',', found '@'|安全下标", "安全下标"),
    (r"FQLAttribute|\.limit\(|分页", "FQL分页"),
    (r"QueryOperator|类型.*匹配", "QueryOperator类型"),
    (r"cannot find|找不到|cannot resolve", "找不到符号"),
    (r"接口已过期|deprecated", "废弃API"),
    (r"Static type checking|静态类型", "静态类型检查"),
]


def _ensure_memory_dir():
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def _load_memory() :
    """加载记忆文件。"""
    _ensure_memory_dir()
    if not MEMORY_FILE.exists():
        return {"entries": [], "stats": {}}
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": [], "stats": {}}


def _save_memory(data: dict):
    _ensure_memory_dir()
    MEMORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_error(error_text: str) -> str:
    """根据错误文本分类错误类型。"""
    if not error_text:
        return "其他"
    text = error_text[:500].lower()
    for pattern, etype in ERROR_TYPE_RULES:
        if re.search(pattern, text, re.I):
            return etype
    return "其他"


def add_fix_memory(error_type: str, error_snippet: str, fix_snippet: str, fix_rule: str = ""):
    """记录一次修复到记忆。"""
    data = _load_memory()
    entries = data.get("entries", [])
    # 取错误和修复的关键片段（避免过长）
    err_short = (error_snippet or "")[:300].strip()
    fix_short = (fix_snippet or "")[:400].strip()
    entry = {
        "type": error_type,
        "error_snippet": err_short,
        "fix_snippet": fix_short,
        "fix_rule": (fix_rule or "")[:200],
        "count": 1,
        "last_seen": time.strftime("%Y-%m-%d %H:%M"),
    }
    # 若已有同类型且 error_snippet 相似，则增加 count
    merged = False
    for e in entries:
        if e.get("type") == error_type and _snippet_similar(err_short, e.get("error_snippet", "")):
            e["count"] = e.get("count", 1) + 1
            e["last_seen"] = entry["last_seen"]
            if fix_short and not e.get("fix_snippet"):
                e["fix_snippet"] = fix_short
            if fix_rule and not e.get("fix_rule"):
                e["fix_rule"] = fix_rule
            merged = True
            break
    if not merged:
        entries.append(entry)
    # 限制条目数量，保留最近 100 条
    data["entries"] = entries[-100:]
    data["stats"] = _compute_stats(data["entries"])
    _save_memory(data)
    print(f"  [Memory] 已记录修复：{error_type}（共 {len(entries)} 条记忆）")


def _snippet_similar(a: str, b: str) -> bool:
    """判断两段错误文本是否相似（简单关键词重叠）。"""
    if not a or not b:
        return False
    words_a = set(re.findall(r"\w+", a[:200]))
    words_b = set(re.findall(r"\w+", b[:200]))
    overlap = len(words_a & words_b) / max(1, min(len(words_a), len(words_b)))
    return overlap > 0.3


def _compute_stats(entries: list) :
    """统计各类型出现次数。"""
    stats = {}
    for e in entries:
        t = e.get("type", "其他")
        stats[t] = stats.get(t, 0) + e.get("count", 1)
    return stats


def query_similar_fixes(error_text: str, limit: int = 3) -> list:
    """根据错误文本检索相似的历史修复。"""
    data = _load_memory()
    entries = data.get("entries", [])
    if not entries:
        return []
    etype = classify_error(error_text)
    # 优先同类型，再按 error_snippet 相似度
    scored = []
    for e in entries:
        score = 2 if e.get("type") == etype else 0
        if _snippet_similar(error_text[:300], e.get("error_snippet", "")):
            score += 3
        if score > 0 or etype == "其他":
            scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


def build_memory_prompt_context(error_text: str) -> str:
    """根据错误文本构建注入 prompt 的记忆上下文。"""
    similar = query_similar_fixes(error_text)
    if not similar:
        return ""
    lines = ["\n## 历史类似修复（可直接参考）\n"]
    for i, e in enumerate(similar, 1):
        t = e.get("type", "?")
        rule = e.get("fix_rule", "")
        fix = e.get("fix_snippet", "")[:200]
        lines.append(f"{i}. [{t}] {rule}")
        if fix:
            lines.append(f"   修复示例：{fix}...")
        lines.append("")
    return "\n".join(lines)
