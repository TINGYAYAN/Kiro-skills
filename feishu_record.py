"""
飞书记录模块：部署成功后，将函数信息追加到飞书表格；同时支持批量读取/更新。

支持两种输出方式（在 config 的 feishu 下配置）：
1. spreadsheet：电子表格（推荐，更简单），需配置 spreadsheet_token
2. bitable：多维表格，需配置 bitable_app_token、bitable_table_id

多维表格列说明：
  - 描述      ← 用户填写需求（批量模式的输入）
  - 绑定对象  ← 用户填写对象名称，如"客户"、"AccountObj"
  - 函数名    ← 自动填入（部署成功后）
  - 系统API名 ← 自动填入
  - 状态      ← 自动填入（待执行 / ✅成功 / ❌失败）
  - 执行时间  ← 自动填入
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

FIELD_FUNC_NAME = "函数名"
FIELD_DESC = "描述"
FIELD_OBJECT = "绑定对象"
FIELD_API_NAME = "系统API名"
FIELD_STATUS = "状态"
FIELD_EXEC_TIME = "执行时间"

STATUS_PENDING = "⏳待执行"
STATUS_RUNNING = "🔄执行中"
STATUS_OK = "✅成功"
STATUS_FAIL = "❌失败"

FEISHU_API = "https://open.feishu.cn/open-apis"


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
    从多维表格读取「待执行」记录：描述不为空 且 函数名为空 且 状态不是"执行中"。
    每条记录返回 {record_id, 描述, 绑定对象}。
    """
    feishu = cfg.get("feishu") or {}
    app_id = feishu.get("app_id")
    app_secret = feishu.get("app_secret")
    app_token = feishu.get("bitable_app_token")
    table_id = feishu.get("bitable_table_id")
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
            status = (f.get(FIELD_STATUS) or "").strip()
            # 只捡「描述已填、函数名为空、且尚未开始执行」的行
            # status 为空 或 STATUS_PENDING 才捡起；已成功/失败/执行中一律跳过
            status_is_new = status in ("", STATUS_PENDING)
            if desc and not func_name and status_is_new:
                records.append({
                    "record_id": item["record_id"],
                    FIELD_DESC: desc,
                    FIELD_OBJECT: (f.get(FIELD_OBJECT) or "").strip(),
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
    app_token = feishu.get("bitable_app_token")
    table_id = feishu.get("bitable_table_id")
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
    app_token = feishu["bitable_app_token"]
    table_id = feishu["bitable_table_id"]

    _ensure_table_fields(token, app_token, table_id,
                         extra=[FIELD_STATUS, FIELD_EXEC_TIME])

    for rec in records:
        fields = {
            FIELD_FUNC_NAME: "",
            FIELD_API_NAME: "",
            FIELD_STATUS: STATUS_PENDING,
            FIELD_EXEC_TIME: datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        _update_bitable_record(token, app_token, table_id, rec["record_id"], fields)

    return len(records)


def mark_bitable_record(cfg: dict, record_id: str, status: str,
                        func_name: str = "", api_name: str = "", error: str = "") -> None:
    """更新多维表格中指定记录的状态、函数名、系统API名。"""
    import datetime

    feishu = cfg.get("feishu") or {}
    token = _get_tenant_token(feishu["app_id"], feishu["app_secret"])
    app_token = feishu["bitable_app_token"]
    table_id = feishu["bitable_table_id"]

    # 确保状态和时间列存在
    _ensure_table_fields(token, app_token, table_id,
                         extra=[FIELD_STATUS, FIELD_EXEC_TIME])

    fields: dict = {FIELD_STATUS: status}
    fields[FIELD_EXEC_TIME] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if func_name:
        fields[FIELD_FUNC_NAME] = func_name
    if api_name:
        fields[FIELD_API_NAME] = api_name
    if error:
        fields[FIELD_STATUS] = f"{STATUS_FAIL}：{error[:80]}"

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
    open_id = feishu.get("notify_open_id")
    if not all([app_id, app_secret, open_id]):
        return False

    try:
        token = _get_tenant_token(app_id, app_secret)
        payload = {
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        req = urllib.request.Request(
            f"{FEISHU_API}/im/v1/messages?receive_id_type=open_id",
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
