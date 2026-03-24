"""
部署可信度校验：检查生成代码中使用的字段是否来自字段缓存，输出可信度报告。
"""
from __future__ import annotations

import re
from pathlib import Path


def _extract_field_apis_from_code(code: str) -> set[str]:
    """从 APL 代码中提取使用的字段 API 名（不含对象 API、标准方法）。"""
    # context.data.xxx, ["field"] in QueryOperator, .get("field"), "field" in Map
    apis = set()
    # context.data.xxx 或 context.data["xxx"]
    for m in re.finditer(r'context\.data\.([a-zA-Z_][a-zA-Z0-9_]*)', code):
        apis.add(m.group(1))
    for m in re.finditer(r'context\.data\[["\']([a-zA-Z_][a-zA-Z0-9_]*(?:__c)?)["\']\]', code):
        apis.add(m.group(1))
    # QueryOperator 中的 "field" 或 'field'
    for m in re.finditer(r'["\']([a-zA-Z_][a-zA-Z0-9_]*(?:__c)?)["\']\s*:', code):
        apis.add(m.group(1))
    for m in re.finditer(r':\s*QueryOperator\.\w+\([^)]*["\']([a-zA-Z_][a-zA-Z0-9_]*(?:__c)?)["\']', code):
        apis.add(m.group(1))
    # .get("field") 或 ["field"]
    for m in re.finditer(r'\.get\(["\']([a-zA-Z_][a-zA-Z0-9_]*(?:__c)?)["\']\)', code):
        apis.add(m.group(1))
    for m in re.finditer(r'\[["\']([a-zA-Z_][a-zA-Z0-9_]*(?:__c)?)["\']\]', code):
        apis.add(m.group(1))
    # .put("field", value) 或 put("field",
    for m in re.finditer(r'\.put\(["\']([a-zA-Z_][a-zA-Z0-9_]*(?:__c)?)["\']', code):
        apis.add(m.group(1))
    # 排除对象 API、标准字段
    skip = {"_id", "name", "data", "dataList", "content", "errorCode", "errorMessage"}
    return {a for a in apis if a not in skip and not a.endswith("Obj")}


def check_credibility(apl_file: str, fields_map: dict, req: dict = None) :
    """校验代码中使用的字段是否在字段缓存中。
    返回 {credible: bool, used_known: list, used_unknown: list, summary: str}"""
    if not Path(apl_file).exists():
        return {"credible": True, "used_known": [], "used_unknown": [], "summary": "无法读取文件"}
    code = Path(apl_file).read_text(encoding="utf-8")
    used = _extract_field_apis_from_code(code)
    if not used:
        return {"credible": True, "used_known": [], "used_unknown": [], "summary": "未检测到需校验的字段引用"}

    known_apis = set()
    for obj_api, fields in (fields_map or {}).items():
        for f in fields or []:
            known_apis.add(f.get("api", ""))

    used_known = [u for u in used if u in known_apis]
    used_unknown = [u for u in used if u not in known_apis]
    credible = len(used_unknown) == 0

    if credible:
        summary = f"字段可信度 ✓ 全部来自缓存（{len(used_known)} 个）"
    else:
        summary = f"字段可信度 ⚠ 存在未确认字段: {', '.join(sorted(used_unknown)[:5])}{'...' if len(used_unknown) > 5 else ''}，建议人工核查"
    return {
        "credible": credible,
        "used_known": sorted(used_known),
        "used_unknown": sorted(used_unknown),
        "summary": summary,
    }
