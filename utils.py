"""公共工具函数。"""
import os
import re
from pathlib import Path
from typing import Optional

import yaml

TOOLS_DIR = Path(__file__).parent

# 对象中文名 → API 名映射（用于推断关联对象、批量模式等）
OBJECT_LABEL_TO_API: dict[str, str] = {
    "租户": "tenant__c",
    "客户": "AccountObj",
    "线索": "LeadsObj",
    "商机": "NewOpportunityObj",
    "联系人": "ContactObj",
    "特价申请": "special_price__c",
    "特配申请": "special_configuration_application__c",
    "特殊配置申请": "special_configuration_application__c",
    "订货单": "SalesOrderObj__c",
    "回款": "PaymentObj",
    "银行流水": "BankFlowObj",
    "提货单": "DeliveryOrderObj",
    "销售订单": "SalesOrderObj__c",
}

# 函数类型 → 命名空间 映射（新建函数时纷享下拉框的选项）
# 命名空间在纷享 UI 中可能分组展示，如：平台(流程/计划任务/自定义控制器)、对象(按钮/UI事件)等
FUNCTION_TYPE_TO_NAMESPACE = {
    "流程函数": "流程",
    "UI函数": "UI事件",
    "同步前函数": "流程",
    "同步后函数": "流程",
    "自定义控制器": "自定义控制器",
    "计划任务": "计划任务",
    "按钮": "按钮",
    "按钮函数": "按钮",
    "校验函数": "校验函数",
    "范围规则": "范围规则",
    "自增编号": "自增编号",
    "导入": "导入",
    "关联对象范围规则": "关联对象范围规则",
    "强制通知": "强制通知",
    "促销": "促销",
    "金蝶云星空": "金蝶云星空",
    "数据集成": "数据集成",
}

# 命名空间 → 代码名称前缀（格式：【流程】、【按钮】等）
NAMESPACE_TO_CODE_PREFIX = {
    "流程": "【流程】",
    "按钮": "【按钮】",
    "范围规则": "【范围规则】",
    "自定义控制器": "【自定义控制器】",
    "UI事件": "【UI事件】",
    "计划任务": "【计划任务】",
    "校验函数": "【校验函数】",
    "自增编号": "【自增编号】",
    "导入": "【导入】",
    "关联对象范围规则": "【关联对象范围规则】",
    "强制通知": "【强制通知】",
    "促销": "【促销】",
    "金蝶云星空": "【金蝶云星空】",
    "数据集成": "【数据集成】",
}

# 英文/简写 → 标准函数类型（req.yml 中 function_type 的别名）
FUNCTION_TYPE_ALIASES = {
    "flow": "流程函数",
    "process": "流程函数",
    "range_rule": "范围规则",
    "scope_rule": "范围规则",
    "ui": "UI函数",
    "ui_event": "UI函数",
    "button": "按钮",
    "btn": "按钮",
    "sync_before": "同步前函数",
    "sync_after": "同步后函数",
    "custom_controller": "自定义控制器",
    "controller": "自定义控制器",
    "scheduled_task": "计划任务",
    "cron": "计划任务",
    "schedule": "计划任务",
    "scheduler": "计划任务",
    "定时任务": "计划任务",
    "validation": "校验函数",
    "validate": "校验函数",
    "auto_number": "自增编号",
    "import": "导入",
    "关联对象范围": "关联对象范围规则",
    "流程": "流程函数",
}


def sync_function_type_from_trigger_type(req: dict) -> None:
    """若未写 function_type，用 trigger_type / triggerType（与部分 req 模板一致）补全。"""
    ft_raw = req.get("function_type")
    if ft_raw is not None and str(ft_raw).strip() != "":
        return
    tt = req.get("trigger_type")
    if tt is None or str(tt).strip() == "":
        tt = req.get("triggerType")
    if tt is None or str(tt).strip() == "":
        return
    key = str(tt).strip().lower()
    mapped = FUNCTION_TYPE_ALIASES.get(key, str(tt).strip())
    req["function_type"] = mapped


def infer_function_type_into_req_if_missing(req: dict) -> None:
    """仅当未填写 function_type 时，从 requirement 推断计划任务等类型。"""
    ft_raw = req.get("function_type")
    if ft_raw is not None and str(ft_raw).strip() != "":
        return
    text = req.get("requirement") or ""
    if not isinstance(text, str):
        text = str(text)
    if "不是计划任务" in text or "非计划任务" in text:
        return
    tl = text.lower()
    if any(k in text for k in ("计划任务", "定时任务", "定时执行", "定时同步", "定时跑批")):
        req["function_type"] = "计划任务"
        return
    if "scheduled_task" in tl or re.search(r"\bcron\b", tl):
        req["function_type"] = "计划任务"


def resolve_namespace(req: dict) -> str:
    """从 req 解析命名空间：优先用 namespace，否则根据 function_type 推断。"""
    ns = (req or {}).get("namespace", "").strip()
    if ns:
        return ns
    ft = (req or {}).get("function_type", "").strip()
    ft = FUNCTION_TYPE_ALIASES.get(ft, ft)
    return FUNCTION_TYPE_TO_NAMESPACE.get(ft, "流程")


def infer_related_objects_from_requirement(
    requirement: str,
    object_api: str = "",
    object_label: str = "",
) -> list[dict]:
    """从需求文本中识别关联对象，返回 [{api, label}, ...]。

    规则：
    - 在 OBJECT_LABEL_TO_API 中查找需求里出现的中文对象名
    - 排除主对象（object_api / object_label）
    - 去重（同一 api 只保留一个）
    """
    text = (requirement or "").strip()
    main_api = (object_api or "").strip()
    main_label = (object_label or "").strip()

    # 主对象对应的所有可能标识（用于排除）
    main_ids = {main_api, main_label}
    reverse = {v: k for k, v in OBJECT_LABEL_TO_API.items()}
    if main_api:
        main_ids.add(reverse.get(main_api, ""))
    if main_label:
        main_ids.add(OBJECT_LABEL_TO_API.get(main_label, ""))

    seen_api: set[str] = set()
    result: list[dict] = []

    # 按标签长度降序，优先匹配长标签（如「特殊配置申请」在「特配申请」前）
    labels_sorted = sorted(OBJECT_LABEL_TO_API.keys(), key=len, reverse=True)

    for label in labels_sorted:
        if label not in text:
            continue
        if label == "回款" and ("近一个月回款" in text or "近一个季度回款" in text or "近半年回款" in text):
            continue
        api = OBJECT_LABEL_TO_API[label]
        if api in main_ids or label in main_ids:
            continue
        if api in seen_api:
            continue
        seen_api.add(api)
        result.append({"api": api, "label": label})

    return result


def infer_short_code_summary(requirement: str, object_label: str = "") -> str:
    """从需求文本提炼代码名称概括（不含前缀），如「按组织机构代码关联租户客户」。
    提炼规则：提取关键字段+动作+对象，形成有业务含义的简短概括。"""
    text = (requirement or "").strip().replace("\n", " ")
    obj = (object_label or "").strip()

    # 关键业务字段（用于提炼）
    key_fields = []
    for kw in ["组织机构代码", "统一信用代码", "企业名称", "客户名称", "手机号", "邮箱", "合同", "订单"]:
        if kw in text:
            key_fields.append(kw)

    # 触发时机前缀：根据描述**开头**（前 15 字）判断触发时机
    # 「变更时」优先于「新建时」，因为变更类需求可能同时包含「新建客户」的操作描述
    trigger_prefix = ""
    head = text[:15]
    if any(kw in head for kw in ["变更时", "修改时", "更新时", "变化时", "代码变更"]):
        trigger_prefix = "变更时"
    elif any(kw in head for kw in ["新建时", "新建租户时", "新建客户时", "创建时"]):
        trigger_prefix = "新建时"

    # 模式1：根据X查找/关联Y → 按X关联Y（提炼关键字段）
    if "组织机构代码" in text and ("关联" in text or "查找" in text) and "客户" in text:
        base = "按组织机构代码关联租户客户" if obj == "租户" else "按组织机构代码关联客户"
        return f"{base}_{trigger_prefix}" if trigger_prefix else base
    if "组织机构代码" in text and "关联" in text:
        base = "组织机构代码关联"
        return f"{base}_{trigger_prefix}" if trigger_prefix else base
    if "统一信用代码" in text and ("查找" in text or "关联" in text):
        return "按统一信用代码关联" + (obj or "")

    # 模式2：关联 + 源对象 + 目标对象
    if "关联" in text and "客户" in text:
        if obj == "租户":
            return "租户关联客户"
        if obj == "商机":
            return "商机关联客户"
        return "关联客户"

    # 模式3：赋值（源→目标）
    if "赋值" in text and key_fields:
        field = key_fields[0][:4]  # 组织机构代码→组织机构
        return f"{obj or ''}字段赋值{field}" if obj else f"赋值{field}"

    # 模式4：新建 + 对象
    if "新建" in text and obj:
        if "客户" in text:
            return f"{obj}新建关联客户"
        return f"{obj}新建"

    # 模式5：更新
    if "更新" in text and obj:
        return f"{obj}更新"

    # 兜底：取首句核心词（去掉前缀），保留 6～10 字
    first = text.split("。")[0].split("，")[0]
    for prefix in ["新建", "当", "根据", "在", "如果", "当"]:
        if first.startswith(prefix):
            first = first[len(prefix):].lstrip("，。、")
    first = re.sub(r"[，。\s！!？?：:]", "", first)
    return first[:10] if len(first) > 10 else (first or "函数")


def load_config(config_path: Optional[str] = None) -> dict:
    """加载配置文件，优先读取 config.local.yml，否则读取 config.yml。"""
    if config_path:
        path = Path(config_path)
    else:
        local = TOOLS_DIR / "config.local.yml"
        path = local if local.exists() else TOOLS_DIR / "config.yml"

    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))

    # 环境变量覆盖敏感字段
    if os.environ.get("ANTHROPIC_API_KEY"):
        cfg.setdefault("llm", {})["api_key"] = os.environ["ANTHROPIC_API_KEY"]
    if os.environ.get("OPENAI_API_KEY"):
        cfg.setdefault("llm", {})["api_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("FX_USERNAME"):
        cfg.setdefault("fxiaoke", {})["username"] = os.environ["FX_USERNAME"]
    if os.environ.get("FX_PASSWORD"):
        cfg.setdefault("fxiaoke", {})["password"] = os.environ["FX_PASSWORD"]

    return cfg
