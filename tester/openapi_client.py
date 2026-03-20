"""
纷享销客 OpenAPI 客户端

支持新版（/oauth2.0/token + Header 鉴权）和旧版（corpAccessToken + body 参数）两套 API。
自动优先使用新版，旧版作为降级。

新版鉴权：
  POST /oauth2.0/token → accessToken + ea + openUserId
  请求头：Authorization: Bearer {accessToken}, x-fs-ea: {ea}, x-fs-userid: {userId}
  数据接口：POST /cgi/crm/v2/data/query?thirdTraceId={UUID}

旧版鉴权（已废弃但仍可用）：
  POST /cgi/corpAccessToken/get/V2 → corpAccessToken
  Body 参数：corpAccessToken + corpId + currentOpenUserId
"""
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config


class FxOpenAPIError(Exception):
    pass


class FxOpenAPIClient:
    """纷享销客 OpenAPI 客户端，自动管理 token 缓存，优先使用新版 Header 鉴权。"""

    TOKEN_EXPIRE_BUFFER = 300  # token 到期前 5 分钟刷新

    def __init__(self, cfg: dict):
        oa = cfg["openapi"]
        self.app_id: str = oa["app_id"]
        self.app_secret: str = oa["app_secret"]
        self.permanent_code: str = (
            oa.get("permanent_code") or oa.get("permanentCode") or oa["app_secret"]
        )
        self.corp_id: str = oa["corp_id"]
        self.base_url: str = oa.get("base_url", "https://open.fxiaoke.com").rstrip("/")

        # 新版鉴权状态
        self._access_token: Optional[str] = None
        self._ea: str = ""
        self._fs_userid: str = oa.get("fs_userid", "")   # x-fs-userid（员工ID）
        self._token_expire_at: float = 0.0

        # 旧版 corpAccessToken（备用）
        self._corp_token: Optional[str] = None
        self._corp_token_expire_at: float = 0.0
        self._open_user_id: str = oa.get("current_open_user_id", "")

        # 用于回退查询员工 ID 的手机号
        self._lookup_phone: str = (cfg.get("fxiaoke") or {}).get("username", "")

    # ------------------------------------------------------------------ #
    # 新版鉴权（/oauth2.0/token）
    # ------------------------------------------------------------------ #

    def _ensure_access_token(self):
        if self._access_token and time.time() < self._token_expire_at - self.TOKEN_EXPIRE_BUFFER:
            return
        self._fetch_access_token()

    def _fetch_access_token(self):
        url = f"{self.base_url}/oauth2.0/token"
        payload = {
            "appId": self.app_id,
            "appSecret": self.app_secret,
            "permanentCode": self.permanent_code,
            "grantType": "app_secret",
        }
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("errorCode") != 0:
            raise FxOpenAPIError(f"获取 accessToken 失败: {data}")
        self._access_token = data["accessToken"]
        self._ea = data.get("ea", "")
        self._token_expire_at = time.time() + data.get("expiresIn", 7200)

    def _new_headers(self) -> dict:
        """构建新版 API 请求头。"""
        self._ensure_access_token()
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "x-fs-ea": self._ea,
            "Content-Type": "application/json",
        }
        userid = self._fs_userid or self._open_user_id
        if userid:
            headers["x-fs-userid"] = userid
        return headers

    def _new_post(self, path: str, data_body: dict) -> dict:
        """使用新版 Header 鉴权调用接口。"""
        trace_id = str(uuid.uuid4())
        url = f"{self.base_url}{path}?thirdTraceId={trace_id}"
        payload = {"data": data_body}
        resp = requests.post(url, json=payload, headers=self._new_headers(), timeout=15)
        resp.raise_for_status()
        result = resp.json()
        if result.get("errorCode") != 0:
            raise FxOpenAPIError(
                f"API 错误 [{path}]: {result.get('errorMessage')} "
                f"(code={result.get('errorCode')})"
            )
        return result

    # ------------------------------------------------------------------ #
    # 旧版鉴权（corpAccessToken，备用）
    # ------------------------------------------------------------------ #

    def _ensure_token(self):
        """旧版 corpAccessToken。"""
        if self._corp_token and time.time() < self._corp_token_expire_at - self.TOKEN_EXPIRE_BUFFER:
            return
        url = f"{self.base_url}/cgi/corpAccessToken/get/V2"
        payload = {
            "appId": self.app_id,
            "appSecret": self.app_secret,
            "permanentCode": self.permanent_code,
        }
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("errorCode") != 0:
            raise FxOpenAPIError(f"获取旧版 Token 失败: {data}")
        self._corp_token = data["corpAccessToken"]
        self._corp_token_expire_at = time.time() + data.get("expiresIn", 7200)
        # 同步 _token 属性供兼容代码使用
        self._token = self._corp_token
        self._token_expire_at = self._corp_token_expire_at

    def _old_post(self, path: str, body: dict) -> dict:
        """使用旧版 body 参数调用接口（需要 currentOpenUserId）。"""
        self._ensure_token()
        url = f"{self.base_url}{path}"
        payload = {
            "corpAccessToken": self._corp_token,
            "corpId": self.corp_id,
            "currentOpenUserId": self._open_user_id,
            **body,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errorCode") != 0:
            raise FxOpenAPIError(
                f"API 错误 [{path}]: {data.get('errorMessage')} (code={data.get('errorCode')})"
            )
        return data

    # ------------------------------------------------------------------ #
    # 对象查询（新版格式，自动降级到旧版）
    # ------------------------------------------------------------------ #

    def find(self, object_api: str, filters: Optional[List[dict]] = None,
             columns: Optional[List[str]] = None, limit: int = 20, offset: int = 0) -> List[dict]:
        """查询对象记录列表。优先新版 API，失败则降级到旧版。"""
        # 尝试新版 /cgi/crm/v2/data/query
        try:
            data_body = {
                "dataObjectApiName": object_api,
                "find_explicit_total_num": False,
                "search_query_info": {
                    "filters": filters or [],
                    "fieldProjection": columns or [],
                    "limit": limit,
                    "offset": offset,
                    "orders": [],
                },
            }
            result = self._new_post("/cgi/crm/v2/data/query", data_body)
            # 新版返回格式
            raw = result.get("data", {})
            if isinstance(raw, list):
                return raw
            return raw.get("dataList", []) or raw.get("records", []) or []
        except FxOpenAPIError as e:
            err_str = str(e)
            # 降级到旧版（需要 currentOpenUserId）
            if self._open_user_id:
                body: dict[str, Any] = {
                    "objectApiName": object_api,
                    "searchQuery": {
                        "filters": filters or [],
                        "columns": columns or [],
                        "limit": limit,
                        "offset": offset,
                    },
                }
                old_result = self._old_post("/cgi/crm/custom/v2/data/query", body)
                return old_result.get("data", {}).get("dataList", [])
            raise

    def find_by_id(self, object_api: str, record_id: str,
                   columns: Optional[List[str]] = None) -> Optional[dict]:
        """按 ID 查询单条记录。"""
        try:
            data_body = {
                "dataObjectApiName": object_api,
                "objectDataId": record_id,
                "fieldProjection": columns or [],
            }
            result = self._new_post("/cgi/crm/v2/data/get", data_body)
            raw = result.get("data", {})
            return raw if isinstance(raw, dict) else raw.get("dataMap")
        except FxOpenAPIError:
            if self._open_user_id:
                body = {
                    "objectApiName": object_api,
                    "objectDataId": record_id,
                    "columns": columns or [],
                }
                old_result = self._old_post("/cgi/crm/custom/v2/data/get", body)
                return old_result.get("data", {}).get("dataMap")
            raise

    def create(self, object_api: str, fields: dict) -> dict:
        """新建记录，返回创建后的记录（含 _id）。"""
        try:
            data_body = {"dataObjectApiName": object_api, "objectData": fields}
            result = self._new_post("/cgi/crm/v2/data/create", data_body)
            return result.get("data", {})
        except FxOpenAPIError:
            if self._open_user_id:
                body = {"objectApiName": object_api, "objectData": fields}
                old_result = self._old_post("/cgi/crm/custom/v2/data/create", body)
                return old_result.get("data", {})
            raise

    def update(self, object_api: str, record_id: str, fields: dict) -> dict:
        """更新记录。"""
        try:
            data_body = {
                "dataObjectApiName": object_api,
                "objectDataId": record_id,
                "objectData": fields,
            }
            result = self._new_post("/cgi/crm/v2/data/update", data_body)
            return result.get("data", {})
        except FxOpenAPIError:
            if self._open_user_id:
                body = {
                    "objectApiName": object_api,
                    "objectDataId": record_id,
                    "objectData": fields,
                }
                old_result = self._old_post("/cgi/crm/custom/v2/data/update", body)
                return old_result.get("data", {})
            raise

    def delete(self, object_api: str, record_id: str) -> bool:
        """删除记录。"""
        try:
            data_body = {"dataObjectApiName": object_api, "objectDataId": record_id}
            self._new_post("/cgi/crm/v2/data/delete", data_body)
        except FxOpenAPIError:
            if self._open_user_id:
                body = {"objectApiName": object_api, "objectDataId": record_id}
                self._old_post("/cgi/crm/custom/v2/data/delete", body)
            else:
                raise
        return True

    def find_one(self, object_api: str, filters: Optional[List[dict]] = None,
                 columns: Optional[List[str]] = None) -> Optional[dict]:
        """查询满足条件的第一条记录。"""
        results = self.find(object_api, filters, columns, limit=1)
        return results[0] if results else None

    # ------------------------------------------------------------------ #
    # 过滤条件构建辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def eq(field: str, value: Any) -> dict:
        return {"field_name": field, "field_values": [str(value)], "operator": "EQ"}

    @staticmethod
    def in_(field: str, values: list) -> dict:
        return {"field_name": field, "field_values": [str(v) for v in values], "operator": "IN"}

    @staticmethod
    def contains(field: str, value: str) -> dict:
        return {"field_name": field, "field_values": [value], "operator": "LIKE"}


def get_client(config_path: Optional[str] = None) -> FxOpenAPIClient:
    cfg = load_config(config_path)
    return FxOpenAPIClient(cfg)


if __name__ == "__main__":
    import json
    client = get_client()
    client._ensure_access_token()
    print("accessToken OK:", bool(client._access_token))
    print("ea:", client._ea)
    print("Client 初始化完成")
