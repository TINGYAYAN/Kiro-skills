"""官方 APL 文档链接与本地整理规则摘要。

这份模块只做规则沉淀，不碰现有生成/部署主流程。
生成器与自动修复器都可以复用，确保优先参考官方文档，再参考项目示例。
"""
from __future__ import annotations


OFFICIAL_DOC_LINKS = [
    ("函数与语法总览", "https://www.fxiaoke.com/mob/guide/apl/dist/pages/func-introduce/base/introduce/"),
    ("API / context", "https://www.fxiaoke.com/mob/guide/apl/dist/pages/func-apl/api/context/"),
    ("对象数据 API（新版写法）", "https://www.fxiaoke.com/mob/guide/apl_nc/dist/pages/func-apl/api/ObjectDataAPI/"),
]


def build_official_docs_section() -> str:
    lines = ["**官方文档（实现与 API 签名以文档为准，示例仅辅助）：**"]
    for title, url in OFFICIAL_DOC_LINKS:
        lines.append(f"- {title}：{url}")
    return "\n".join(lines)


CURATED_OFFICIAL_RULES = """
### 官方文档优先规则（本地整理摘要）

1. **实现优先级**：官方文档 > 当前项目成功函数 > 其他项目成功函数 > 历史零散代码。
2. **API 签名**：`Fx.object.find` 必须带 `SelectAttribute`；`Fx.object.create` / `Fx.object.update` 必须走 4 参数签名。
3. **语法限制**：禁止 Elvis `?:`、禁止 `? :` 三元、禁止 `?["key"]`、禁止 `for` 循环；空值与分支统一使用 `if / else`。
4. **QueryTemplate**：优先使用文档与当前项目中已验证的写法；不要发明签名，不要把条件包装成错误的数据结构。
5. **上下文读取**：优先从 `context`、`context.data`、`context.details`、`context.dataList`、`context.arg` 等文档约定入口取值。
6. **字段与选项**：字段 API 名以当前租户元数据为准；单选/多选字段 value 以真实选项值为准，拿不到时保留待确认标记，不要擅自猜测。
7. **日志与错误处理**：关键 API 调用必须有错误处理；普通函数保留必要业务日志，范围规则不写日志。
8. **生成内容约束**：只输出最终可执行代码，不输出中文分析、修复思路、步骤说明或 markdown 围栏。
""".strip()


SCOPE_RULE_OFFICIAL_RULES = """
### 范围规则专属官方约束摘要

1. 范围规则只负责返回过滤条件，不做数据库查询或写操作。
2. 常见返回形式是 `return ["searchCondition": QueryTemplate.AND(...)]` 或 `return [:]`。
3. `QueryTemplate.OR(...)` 虽然属于平台能力的一部分，但是否可用依赖租户能力与场景；默认优先采用更稳妥的多分支返回。
4. 如果确需生成 `QueryTemplate.OR(...)`，必须优先参考官方文档和当前项目中已成功运行的真实示例，不能臆造 `OR(List)` 这类未验证签名。
""".strip()


def build_doc_guardrails(function_type: str = "") -> str:
    parts = [build_official_docs_section(), "", CURATED_OFFICIAL_RULES]
    if function_type in ("范围规则", "关联对象范围规则"):
        parts.extend(["", SCOPE_RULE_OFFICIAL_RULES])
    return "\n".join(parts).strip()
