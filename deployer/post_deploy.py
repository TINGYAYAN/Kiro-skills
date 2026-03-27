from __future__ import annotations

from pathlib import Path


def detect_code_placeholders(apl_file: str) -> list[str]:
    try:
        code = Path(apl_file).read_text(encoding="utf-8")
    except Exception:
        return []

    markers: list[str] = []
    if "TODO_STORE_VALUE_" in code:
        markers.append("TODO_STORE_VALUE_*")
    if "TODO_REPLACE_" in code:
        markers.append("TODO_REPLACE_*")
    if "真实存储值" in code and "请在平台" in code:
        markers.append("待确认选项值说明")
    return markers


def detect_high_risk_patterns(apl_file: str, req: dict | None = None) -> list[str]:
    try:
        code = Path(apl_file).read_text(encoding="utf-8")
    except Exception:
        return []
    issues: list[str] = []
    function_type = ((req or {}).get("function_type") or "").strip()
    namespace = ((req or {}).get("namespace") or "").strip()
    if (
        function_type in ("范围规则", "关联对象范围规则")
        or namespace == "范围规则"
    ) and "QueryTemplate.OR(" in code:
        issues.append("范围规则中使用 QueryTemplate.OR(...)，该语法可能依赖租户已开通 OR 能力，未开通时平台常阻断保存")
    return issues


def summarize_post_deploy(apl_file: str, fields_map: dict | None = None, req: dict | None = None) -> dict:
    warnings: list[str] = []
    placeholders = detect_code_placeholders(apl_file)
    high_risk_patterns = detect_high_risk_patterns(apl_file, req)
    field_warning = ((req or {}).get("_field_warning") or "").strip()
    if field_warning:
        warnings.append(field_warning)
    if placeholders:
        warnings.append(
            "代码包含待人工确认占位符："
            + ", ".join(placeholders)
            + "。已继续发布，后续可人工修改。"
        )
    if high_risk_patterns:
        warnings.extend(high_risk_patterns)

    credibility = None
    try:
        if fields_map:
            from deployer.credibility import check_credibility

            credibility = check_credibility(apl_file, fields_map, req or {})
            if credibility and (not credibility.get("credible")) and credibility.get("used_unknown"):
                warnings.append(credibility["summary"])
    except Exception:
        credibility = None

    if placeholders or high_risk_patterns:
        risk_level = "高"
        if high_risk_patterns:
            manual_action = "人工确认当前租户是否已开通 OR 能力；若未开通，将多条件 OR 改成分支返回不同 AND 条件后重新发布"
        else:
            manual_action = "人工核对占位符和字段真实值后修改函数并重新发布"
    elif field_warning:
        risk_level = "中"
        manual_action = "人工补齐选项真实值后核对函数逻辑"
    elif credibility and not credibility.get("credible"):
        risk_level = "中"
        manual_action = "人工核对未确认字段 API 是否正确"
    else:
        risk_level = "低"
        manual_action = ""

    return {
        "warnings": warnings,
        "summary": " | ".join(warnings),
        "placeholders": placeholders,
        "risk_level": risk_level,
        "manual_action": manual_action,
        "credibility": credibility,
    }
