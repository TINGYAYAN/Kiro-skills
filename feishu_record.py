"""
飞书记录模块：部署成功后，将函数信息追加到飞书表格；同时支持批量读取/更新。

支持两种输出方式（在 config 的 feishu 下配置）：
1. spreadsheet：电子表格（推荐，更简单），需配置 spreadsheet_token
2. bitable：多维表格，需配置 bitable_app_token、bitable_table_id

多维表格列说明：
  - 批量模式默认以「多维表格模板」作为输入，不建议只给自然语言长描述而不建结构化列
  - 描述      ← 必填；用户填写需求（批量模式主输入）
  - 绑定对象  ← 推荐填写；用户填写对象名称，如"客户"、"AccountObj"
  - 函数类型 / trigger_type / 触发类型 ← 推荐填写；与 req 一致（如 scheduled_task → 计划任务）
  - 项目      ← 推荐填写；多项目批量时尤其建议明确
  - 函数名    ← 必须留空；自动填入（部署成功后）
  - 系统API名 ← 必须留空；自动填入
  - 状态      ← 自动填入（待执行 / ✅成功 / ❌失败）
  - 执行时间  ← 自动填入
  - 执行反馈  ← 自动填入（成功摘要 / 失败原因全文，便于排查）
  - 风险级别  ← 自动填入（低 / 中 / 高）
  - 人工处理建议 ← 自动填入（需要人工复核或修正时给出建议）

推荐模板列顺序：
  描述 | 绑定对象 | 函数类型 | 项目 | 函数名 | 系统API名 | 状态 | 执行时间 | 执行反馈 | 风险级别 | 人工处理建议
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Optional

FIELD_FUNC_NAME = "函数名"
FIELD_DESC = "描述"
FIELD_OBJECT = "绑定对象"
FIELD_API_NAME = "系统API名"
FIELD_STATUS = "状态"
FIELD_EXEC_TIME = "执行时间"
FIELD_FEEDBACK = "执行反馈"
FIELD_RISK_LEVEL = "风险级别"
FIELD_MANUAL_ACTION = "人工处理建议"
FIELD_TRIGGER_TYPE = "trigger_type"
FIELD_PROJECT = "项目"

STATUS_PENDING = "⏳待执行"
STATUS_RUNNING = "🔄执行中"
STATUS_OK = "✅成功"
STATUS_FAIL = "❌失败"

FEISHU_API = "https://open.feishu.cn/open-apis"
DEFAULT_RUNNING_STALE_MINUTES = 90
ORPHAN_RUNNING_GRACE_MINUTES = 8
LOCK_FILE = Path(__file__).parent / ".batch.lock"
BITABLE_TEMPLATE_COLUMNS = [
    FIELD_DESC,
    FIELD_OBJECT,
    "函数类型",
    FIELD_PROJECT,
    FIELD_FUNC_NAME,
    FIELD_API_NAME,
    FIELD_STATUS,
    FIELD_EXEC_TIME,
    FIELD_FEEDBACK,
    FIELD_RISK_LEVEL,
    FIELD_MANUAL_ACTION,
]
BITABLE_TEMPLATE_EXAMPLES = [
    {
        FIELD_DESC: "通过销售线索的最终客户查客户，匹配后回写客户字段",
        FIELD_OBJECT: "销售线索",
        "函数类型": "流程函数",
        FIELD_PROJECT: "西门子",
    },
    {
        FIELD_DESC: "任务明细的本次联系人仅可选客户联系人",
        FIELD_OBJECT: "任务明细",
        "函数类型": "范围规则",
        FIELD_PROJECT: "西门子",
    },
    {
        FIELD_DESC: "每天汇总近一个月银行流水金额并更新客户季度回款",
        FIELD_OBJECT: "银行流水",
        "函数类型": "计划任务",
        FIELD_PROJECT: "朗润生物",
    },
]
DEFAULT_TEMPLATE_TABLE_NAME = "APL批量生成模板"


def _parse_exec_time(text: str) -> datetime.datetime | None:
    value = (text or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _is_stale_running(status: str, exec_time: str, cfg: dict) -> bool:
    if status != STATUS_RUNNING:
        return False
    started_at = _parse_exec_time(exec_time)
    if started_at is None:
        return False
    feishu = cfg.get("feishu") or {}
    stale_minutes = int(feishu.get("running_stale_minutes", DEFAULT_RUNNING_STALE_MINUTES) or DEFAULT_RUNNING_STALE_MINUTES)
    age = datetime.datetime.now() - started_at
    return age.total_seconds() >= stale_minutes * 60


def _is_orphan_running(status: str, exec_time: str) -> bool:
    if status != STATUS_RUNNING:
        return False
    started_at = _parse_exec_time(exec_time)
    if started_at is None:
        return False
    if LOCK_FILE.exists():
        return False
    age = datetime.datetime.now() - started_at
    return age.total_seconds() >= ORPHAN_RUNNING_GRACE_MINUTES * 60


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    """获取飞书 tenant_access_token。"""
    import urllib.request
    import json

    req = urllib.request.Request(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"飞书鉴权失败: {data}")
    return data["tenant_access_token"]


def _parse_bitable_url(url: str) -> tuple[str, str]:
    text = (url or "").strip()
    if not text:
        return "", ""
    m = re.search(r"/base/([^/?#]+)\?table=([^&#]+)", text)
    if not m:
        return "", ""
    return m.group(1).strip(), m.group(2).strip()


def _resolve_runtime_bitable_target(cfg: dict) -> tuple[str, str]:
    """解析当前批量执行实际使用的 base/table。

    规则：
    1. 若配置了 template_table_url，则优先直接从该链接解析；
    2. 否则回退到 bitable_app_token / bitable_table_id。
    """
    feishu = cfg.get("feishu") or {}
    app_token, table_id = _parse_bitable_url(feishu.get("template_table_url") or "")
    if app_token and table_id:
        return app_token, table_id
    return (
        (feishu.get("bitable_app_token") or "").strip(),
        (feishu.get("bitable_table_id") or "").strip(),
    )


def _list_table_fields(token: str, app_token: str, table_id: str) -> dict[str, str]:
    """获取表字段列表，返回 {字段名: field_id}。"""
    import urllib.request
    import json

    req = urllib.request.Request(
        f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"获取多维表格字段失败: {data.get('msg', data)}")
    items = data.get("data", {}).get("items", [])
    # 飞书返回的字段名键为 field_name（不是 name）
    return {
        f.get("field_name") or f.get("name", ""): f.get("field_id", "")
        for f in items
        if f.get("field_id")
    }


def _create_bitable_table(token: str, app_token: str, table_name: str) -> dict:
    """在指定 base 下创建一张新数据表，返回 table 信息。"""
    import urllib.request
    import json

    req = urllib.request.Request(
        f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables",
        data=json.dumps({"table": {"name": table_name}}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"创建多维表格数据表失败: {data.get('msg', data)}")
    payload = data.get("data", {}) or {}
    if payload.get("table_id") and not payload.get("table"):
        return {
            "table_id": payload.get("table_id"),
            "name": table_name,
        }
    return payload.get("table", {}) or payload


def _create_table_field(token: str, app_token: str, table_id: str, field_name: str) -> str:
    """在多维表格中创建一个文本字段，返回 field_id。"""
    import urllib.request
    import json

    req = urllib.request.Request(
        f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        data=json.dumps({"field_name": field_name, "type": 1}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"创建字段「{field_name}」失败: {data.get('msg', data)}")
    return data.get("data", {}).get("field", {}).get("field_id", "")


def _ensure_table_fields(token: str, app_token: str, table_id: str,
                         extra: list[str] | None = None) -> dict[str, str]:
    """确保多维表格包含所需列，不存在则自动创建，返回 {字段名: field_id}。"""
    required = [FIELD_FUNC_NAME, FIELD_DESC, FIELD_OBJECT, FIELD_API_NAME] + (extra or [])
    fields_map = _list_table_fields(token, app_token, table_id)

    for col in required:
        if col not in fields_map:
            fid = _create_table_field(token, app_token, table_id, col)
            fields_map[col] = fid
            print(f"  [飞书记录] 已创建列「{col}」")

    return fields_map


def _update_bitable_record(
    token: str,
    app_token: str,
    table_id: str,
    record_id: str,
    fields: dict,
) -> None:
    """更新多维表格中指定记录的字段。"""
    import urllib.request
    import json

    payload = {k: str(v) if v is not None else "" for k, v in fields.items()}
    req = urllib.request.Request(
        f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}",
        data=json.dumps({"fields": payload}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"更新记录失败: {data.get('msg', data)}")


def list_bitable_pending_records(cfg: dict) -> list[dict]:
    """
    从多维表格读取「待执行」记录：描述不为空 且 系统API名为空；
    状态为「待执行」、空、或「失败且系统API名为空」（便于失败后无需整表清空即可重跑）。
    每条记录返回 {record_id, 描述, 绑定对象}。
    """
    feishu = cfg.get("feishu") or {}
    app_id = feishu.get("app_id")
    app_secret = feishu.get("app_secret")
    app_token, table_id = _resolve_runtime_bitable_target(cfg)
    if not all([app_id, app_secret, app_token, table_id]):
        raise RuntimeError("缺少飞书多维表格配置（app_id/app_secret/bitable_app_token/bitable_table_id）")

    import urllib.request
    import json

    token = _get_tenant_token(app_id, app_secret)
    records = []
    page_token = None

    while True:
        url = f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") != 0:
            raise RuntimeError(f"读取记录失败: {data.get('msg', data)}")

        items = data.get("data", {}).get("items", [])
        for item in items:
            f = item.get("fields", {})
            desc = (f.get(FIELD_DESC) or "").strip()
            func_name = (f.get(FIELD_FUNC_NAME) or "").strip()
            api_name = (f.get(FIELD_API_NAME) or "").strip()
            status = (f.get(FIELD_STATUS) or "").strip()
            exec_time = (f.get(FIELD_EXEC_TIME) or "").strip()
            # 待执行以「系统API名是否为空」为准，而不是函数名。
            # 这样即使函数名已提前生成，只要还没真正部署出系统 API，仍然会继续执行。
            status_is_pending = status in ("", STATUS_PENDING)
            status_is_retryable_fail = status == STATUS_FAIL and not api_name
            status_is_stale_running = not api_name and _is_stale_running(status, exec_time, cfg)
            status_is_orphan_running = not api_name and _is_orphan_running(status, exec_time)
            if desc and not api_name and (
                status_is_pending or status_is_retryable_fail or status_is_stale_running or status_is_orphan_running
            ):
                trig = (
                    (f.get(FIELD_TRIGGER_TYPE) or f.get("触发类型") or "").strip()
                )
                records.append({
                    "record_id": item["record_id"],
                    FIELD_DESC: desc,
                    FIELD_OBJECT: (f.get(FIELD_OBJECT) or "").strip(),
                    "函数类型": (f.get("函数类型") or "").strip(),
                    "trigger_type": trig,
                    "项目": (f.get("项目") or f.get("project") or "").strip(),
                })

        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")

    return records


def list_bitable_records_with_desc(cfg: dict) -> list[dict]:
    """
    从多维表格读取所有「描述不为空」的记录（不限函数名/状态）。
    用于重新生成模式：先清空这些行的函数名/状态，再批量执行。
    """
    feishu = cfg.get("feishu") or {}
    app_id = feishu.get("app_id")
    app_secret = feishu.get("app_secret")
    app_token, table_id = _resolve_runtime_bitable_target(cfg)
    if not all([app_id, app_secret, app_token, table_id]):
        raise RuntimeError("缺少飞书多维表格配置（app_id/app_secret/bitable_app_token/bitable_table_id）")

    import urllib.request
    import json

    token = _get_tenant_token(app_id, app_secret)
    records = []
    page_token = None

    while True:
        url = f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get("code") != 0:
            raise RuntimeError(f"读取记录失败: {data.get('msg', data)}")

        items = data.get("data", {}).get("items", [])
        for item in items:
            f = item.get("fields", {})
            desc = (f.get(FIELD_DESC) or "").strip()
            if desc:
                records.append({
                    "record_id": item["record_id"],
                    FIELD_DESC: desc,
                    FIELD_OBJECT: (f.get(FIELD_OBJECT) or "").strip(),
                })

        if not data.get("data", {}).get("has_more"):
            break
        page_token = data.get("data", {}).get("page_token")

    return records


def clear_bitable_for_regenerate(cfg: dict) -> int:
    """
    将多维表格中所有「描述不为空」的行的 函数名、系统API名、状态 清空，
    以便重新生成模式能再次执行这些行。
    返回被清空的行数。
    """
    import datetime

    records = list_bitable_records_with_desc(cfg)
    if not records:
        return 0

    feishu = cfg.get("feishu") or {}
    token = _get_tenant_token(feishu["app_id"], feishu["app_secret"])
    app_token, table_id = _resolve_runtime_bitable_target(cfg)

    _ensure_table_fields(token, app_token, table_id,
                         extra=[FIELD_STATUS, FIELD_EXEC_TIME, FIELD_FEEDBACK, FIELD_RISK_LEVEL, FIELD_MANUAL_ACTION])

    for rec in records:
        fields = {
            FIELD_FUNC_NAME: "",
            FIELD_API_NAME: "",
            FIELD_STATUS: STATUS_PENDING,
            FIELD_EXEC_TIME: datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            FIELD_FEEDBACK: "",
            FIELD_RISK_LEVEL: "",
            FIELD_MANUAL_ACTION: "",
        }
        _update_bitable_record(token, app_token, table_id, rec["record_id"], fields)

    return len(records)


def mark_bitable_record(cfg: dict, record_id: str, status: str,
                        func_name: str = "", api_name: str = "", error: str = "",
                        feedback: str = "", risk_level: str = "", manual_action: str = "") -> None:
    """更新多维表格中指定记录的状态、函数名、系统API名、执行反馈。"""
    import datetime

    feishu = cfg.get("feishu") or {}
    token = _get_tenant_token(feishu["app_id"], feishu["app_secret"])
    app_token, table_id = _resolve_runtime_bitable_target(cfg)

    _ensure_table_fields(token, app_token, table_id,
                         extra=[FIELD_STATUS, FIELD_EXEC_TIME, FIELD_FEEDBACK, FIELD_RISK_LEVEL, FIELD_MANUAL_ACTION])

    fields: dict = {FIELD_STATUS: status}
    fields[FIELD_EXEC_TIME] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if status in (STATUS_RUNNING, STATUS_OK):
        fields[FIELD_RISK_LEVEL] = ""
        fields[FIELD_MANUAL_ACTION] = ""
    if func_name:
        fields[FIELD_FUNC_NAME] = func_name
    if api_name:
        fields[FIELD_API_NAME] = api_name
    if error:
        fields[FIELD_STATUS] = STATUS_FAIL
        fields[FIELD_FEEDBACK] = error[:2000]
    elif feedback:
        fields[FIELD_FEEDBACK] = feedback[:2000]
    if risk_level:
        fields[FIELD_RISK_LEVEL] = risk_level
    if manual_action:
        fields[FIELD_MANUAL_ACTION] = manual_action[:500]

    _update_bitable_record(token, app_token, table_id, record_id, fields)


def _create_bitable_record(
    token: str,
    app_token: str,
    table_id: str,
    fields_map: dict[str, str],
    record: dict[str, str],
) -> Optional[str]:
    """在多维表格中创建一条记录，返回记录 ID 或 None。"""
    import urllib.request
    import json

    # 直接用字段名作 key（飞书 bitable 记录接口要求字段名，不是 field_id）
    payload = {}
    for field_name, value in record.items():
        if field_name in fields_map and value is not None:
            payload[field_name] = str(value).strip()

    if not payload:
        return None

    req = urllib.request.Request(
        f"{FEISHU_API}/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        data=json.dumps({"fields": payload}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"创建多维表格记录失败: {data.get('msg', data)}")
    rec = data.get("data", {}).get("record", {})
    return rec.get("record_id")


def create_bitable_template_table(
    cfg: dict,
    table_name: str = "APL批量生成模板",
    with_examples: bool = True,
) -> dict:
    """在当前 bitable base 下创建一张批量生成模板表，并按需写入示例行。"""
    feishu = cfg.get("feishu") or {}
    app_id = feishu.get("app_id")
    app_secret = feishu.get("app_secret")
    app_token = feishu.get("bitable_app_token")
    if not all([app_id, app_secret, app_token]):
        raise RuntimeError("缺少飞书多维表格配置（app_id/app_secret/bitable_app_token）")

    token = _get_tenant_token(app_id, app_secret)
    table = _create_bitable_table(token, app_token, table_name)
    table_id = table.get("table_id") or table.get("tableId") or ""
    if not table_id:
        raise RuntimeError(f"创建模板表后未返回 table_id: {table}")

    fields_map = _ensure_table_fields(token, app_token, table_id, extra=BITABLE_TEMPLATE_COLUMNS)

    created_records = 0
    if with_examples:
        for record in BITABLE_TEMPLATE_EXAMPLES:
            if _create_bitable_record(token, app_token, table_id, fields_map, record):
                created_records += 1

    return {
        "app_token": app_token,
        "table_id": table_id,
        "table_name": table.get("name") or table_name,
        "url": f"https://feishu.cn/base/{app_token}?table={table_id}",
        "created_records": created_records,
    }


def get_fixed_bitable_template_info(cfg: dict) -> dict:
    """返回配置中的固定模板表信息；未配置时返回默认占位信息。"""
    feishu = cfg.get("feishu") or {}
    url = (feishu.get("template_table_url") or "").strip()
    table_name = (feishu.get("template_table_name") or DEFAULT_TEMPLATE_TABLE_NAME).strip() or DEFAULT_TEMPLATE_TABLE_NAME
    if not url:
        return {
            "table_name": table_name,
            "url": "",
            "is_fixed": False,
        }
    return {
        "table_name": table_name,
        "url": url,
        "is_fixed": True,
    }


def build_bitable_template_reply(template_info: dict) -> str:
    """生成可直接发给用户的模板表说明文案。仅返回文本，不主动发送。"""
    url = (template_info or {}).get("url") or ""
    table_name = (template_info or {}).get("table_name") or DEFAULT_TEMPLATE_TABLE_NAME
    template_line = f"模板表：{table_name}\n链接：{url}\n\n" if url else ""
    return (
        f"批量生成请先按飞书多维表格模板填写需求。\n\n"
        f"{template_line}"
        f"推荐列：描述｜绑定对象｜函数类型｜项目｜函数名｜系统API名｜状态｜执行时间｜执行反馈｜风险级别｜人工处理建议\n"
        f"至少填写：描述\n"
        f"推荐填写：绑定对象、函数类型、项目\n"
        f"函数名、系统API名请留空，系统会自动识别为待执行并回填结果。"
    )


def _append_to_spreadsheet(
    token: str,
    spreadsheet_token: str,
    func_name: str,
    description: str,
    object_label: str,
    func_api_name: str,
) -> str:
    """向电子表格追加一行数据。"""
    import urllib.request
    import json

    # 获取 spreadsheet 元数据（含 sheets 列表）
    req = urllib.request.Request(
        f"{FEISHU_API}/sheets/v3/spreadsheets/{spreadsheet_token}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"获取电子表格信息失败: {data.get('msg', data)}")
    d = data.get("data", {})
    sheets = d.get("spreadsheet", {}).get("sheets") or d.get("sheets", [])
    if not sheets:
        raise RuntimeError("电子表格中没有工作表")
    sheet_id = sheets[0].get("sheet_id", "0")

    # 追加一行（range 格式：sheetId!A:D，INSERT_ROWS 在末尾插入）
    values = [[func_name, description, object_label, func_api_name or ""]]
    payload = {
        "valueRange": {
            "range": f"{sheet_id}!A:D",
            "values": values,
        },
        "insertDataOption": "INSERT_ROWS",
    }
    req = urllib.request.Request(
        f"{FEISHU_API}/sheets/v2/spreadsheets/{spreadsheet_token}/values_append",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data.get("code") != 0:
        raise RuntimeError(f"电子表格追加失败: {data.get('msg', data)}")

    return f"https://feishu.cn/sheets/{spreadsheet_token}"


def append_func_to_feishu(
    func_name: str,
    description: str,
    object_label: str,
    func_api_name: str,
    cfg: dict,
) -> Optional[str]:
    """
    将函数信息追加到飞书表格。
    优先使用电子表格（spreadsheet），未配置则尝试多维表格（bitable）。
    若都未配置则返回 None。
    """
    feishu = cfg.get("feishu") or {}
    app_id = feishu.get("app_id")
    app_secret = feishu.get("app_secret")
    if not app_id or not app_secret:
        return None

    token = _get_tenant_token(app_id, app_secret)

    # 1. 优先：电子表格（更简单）
    spreadsheet_token = feishu.get("spreadsheet_token")
    if spreadsheet_token:
        return _append_to_spreadsheet(
            token, spreadsheet_token,
            func_name, description, object_label, func_api_name,
        )

    # 2. 备选：多维表格
    app_token = feishu.get("bitable_app_token")
    table_id = feishu.get("bitable_table_id")
    if not app_token or not table_id:
        return None

    # 自动确保表格有所需列（没有则创建）
    fields_map = _ensure_table_fields(token, app_token, table_id)
    record = {
        FIELD_FUNC_NAME: func_name,
        FIELD_DESC: description,
        FIELD_OBJECT: object_label,
        FIELD_API_NAME: func_api_name or "",
    }
    record_id = _create_bitable_record(token, app_token, table_id, fields_map, record)
    base_url = f"https://feishu.cn/base/{app_token}?table={table_id}"
    if record_id:
        return f"{base_url}&record={record_id}"
    return base_url


def send_feishu_notify(text: str, cfg: dict) -> bool:
    """向配置的 notify_open_id 发送进度通知消息，失败静默忽略。返回是否发送成功。"""
    import urllib.request
    import json

    feishu = cfg.get("feishu") or {}
    app_id = feishu.get("app_id")
    app_secret = feishu.get("app_secret")
    chat_id = feishu.get("notify_chat_id")
    open_id = feishu.get("notify_open_id")
    receive_id = chat_id or open_id
    receive_id_type = "chat_id" if chat_id else "open_id"
    if not all([app_id, app_secret, receive_id]):
        return False

    try:
        token = _get_tenant_token(app_id, app_secret)
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        req = urllib.request.Request(
            f"{FEISHU_API}/im/v1/messages?receive_id_type={receive_id_type}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        return data.get("code") == 0
    except Exception:
        return False


def collect_func_info(apl_file: str, req: Optional[dict], meta: dict) -> dict:
    """从 APL 文件、req、meta 收集函数信息。"""
    func_name = Path(apl_file).stem
    description = ""
    object_label = ""
    func_api_name = meta.get("func_api_name", "")

    if req:
        raw = (req.get("requirement") or "").strip()
        description = raw.splitlines()[0][:200] if raw else ""
        object_label = req.get("object_label") or req.get("object_api") or ""

    # 从 APL 文件头补充 @description
    try:
        text = Path(apl_file).read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.strip().startswith("@description"):
                desc = line.split("@description", 1)[1].strip()
                if desc and not description:
                    description = desc[:200]
                break
    except Exception:
        pass

    return {
        "func_name": func_name,
        "description": description,
        "object_label": object_label,
        "func_api_name": func_api_name,
    }
