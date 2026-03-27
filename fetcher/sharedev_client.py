"""
ShareDev 证书认证客户端

基于开发者证书调用纷享销客内部 API，实现：
- 拉取租户对象列表
- 拉取对象字段描述
- 拉取 APL 函数列表及代码

证书配置（三选一，优先级从高到低）：
1. 项目根目录 cert.conf： [sharedev] domain= cert=
2. .vscode/settings.json： sharedev.domain、sharedev.certificate
3. config.local.yml： fxiaoke.sharedev_domain、fxiaoke.sharedev_certificate
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
import warnings
from pathlib import Path
from typing import Any, Optional

try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except Exception:
    pass

import requests

_TOOLS = Path(__file__).parent.parent
PROJECT_ROOT = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))


def _parse_cert_conf(content: str) -> dict[str, str]:
    """解析 cert.conf 格式，返回 {sharedev.domain, sharedev.cert}"""
    result: dict[str, str] = {}
    current_section = ""

    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            continue

        sep = line.find("=") if "=" in line else line.find(":")
        if sep < 0:
            continue

        key = line[:sep].strip()
        value = line[sep + 1 :].strip().strip("'\"")
        if current_section:
            result[f"{current_section}.{key}"] = value
        else:
            result[key] = value

    return result


def load_sharedev_config(
    project_root: Optional[Path] = None,
    project_name: Optional[str] = None,
) -> tuple[str, str]:
    """
    加载 ShareDev 证书配置，返回 (domain, certificate)。
    project_name: 多项目时按项目加载，如「硅基流动」会优先找 [sharedev.硅基流动]。
    Raises:
        ValueError: 未找到有效配置
    """
    root = project_root or PROJECT_ROOT

    def _try_cert_data(data: dict, section: str) -> tuple[str, str] | None:
        domain = (data.get(f"{section}.domain") or data.get("domain", "")).strip()
        cert = (data.get(f"{section}.cert") or data.get("cert", "")).strip()
        if domain and cert and cert != "paste_your_cert_here":
            return domain.rstrip("/"), cert
        return None

    # 0. 当指定 project_name 时，优先从 config 的 sharedev_projects 读取，禁止用 cert.conf [sharedev] 作为回退（否则会混用其他项目证书）
    if project_name:
        for name in ["config.local.yml", "config.yml"]:
            cfg_path = _TOOLS / name
            if cfg_path.exists():
                try:
                    import yaml
                    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                    fx = cfg.get("fxiaoke") or {}
                    proj_cfg = (fx.get("sharedev_projects") or {}).get(project_name.strip())
                    if isinstance(proj_cfg, dict):
                        domain = (proj_cfg.get("domain") or proj_cfg.get("sharedev_domain") or "").strip()
                        cert = (proj_cfg.get("certificate") or proj_cfg.get("sharedev_certificate") or "").strip()
                        if domain and cert:
                            return domain.rstrip("/"), cert
                except Exception:
                    pass

    # 1. cert.conf（项目根或 _tools 父级），多项目时优先 [sharedev.项目名]
    for d in [root, _TOOLS.parent]:
        cert_path = d / "cert.conf"
        if cert_path.exists():
            data = _parse_cert_conf(cert_path.read_text(encoding="utf-8"))
            if project_name:
                section = f"sharedev.{project_name.strip()}"
                r = _try_cert_data(data, section)
                if r:
                    return r
            r = _try_cert_data(data, "sharedev")
            if r:
                return r

    # 2. .vscode/settings.json（暂不支持按项目，用 sharedev.domain）
    vs_settings = root / ".vscode" / "settings.json"
    if vs_settings.exists():
        try:
            data = json.loads(vs_settings.read_text(encoding="utf-8"))
            domain = (data.get("sharedev.domain") or "").strip()
            cert = (data.get("sharedev.certificate") or data.get("sharedev.cert") or "").strip()
            if domain and cert:
                return domain.rstrip("/"), cert
        except (json.JSONDecodeError, TypeError):
            pass

    # 3. config.local.yml / config.yml
    for name in ["config.local.yml", "config.yml"]:
        cfg_path = _TOOLS / name
        if cfg_path.exists():
            try:
                import yaml

                cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                fx = cfg.get("fxiaoke") or {}
                if project_name:
                    proj_cfg = (fx.get("sharedev_projects") or {}).get(project_name.strip())
                    if isinstance(proj_cfg, dict):
                        domain = (proj_cfg.get("domain") or proj_cfg.get("sharedev_domain") or "").strip()
                        cert = (proj_cfg.get("certificate") or proj_cfg.get("sharedev_certificate") or "").strip()
                        if domain and cert:
                            return domain.rstrip("/"), cert
                domain = (fx.get("sharedev_domain") or fx.get("base_url") or "").strip()
                cert = (fx.get("sharedev_certificate") or "").strip()
                if domain and cert:
                    return domain.rstrip("/"), cert
            except Exception:
                pass

    raise ValueError(
        "未找到 ShareDev 证书配置。请任选一种方式配置：\n"
        "1. 项目根目录创建 cert.conf，[sharedev] 下填 domain 和 cert\n"
        "2. .vscode/settings.json 中填 sharedev.domain 和 sharedev.certificate\n"
        "3. config.local.yml 的 fxiaoke 下填 sharedev_domain 和 sharedev_certificate"
    )


class ShareDevClient:
    """ShareDev 证书认证 API 客户端"""

    def __init__(self, domain: str, certificate: str):
        self.domain = domain.rstrip("/")
        self.certificate = certificate.strip()
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": self.certificate,
                "Content-Type": "application/json",
            }
        )

    def _request(self, path: str, data: dict[str, Any]) -> dict:
        """POST 请求，path 如 /EMDHFUNC/biz/query，会加上 /FHH 前缀"""
        url = f"{self.domain}/FHH{path}"
        resp = self._session.post(url, json=data, timeout=60)
        resp.raise_for_status()
        result = resp.json()

        status = result.get("Result", {}).get("StatusCode", -1)
        if status != 0:
            msg = result.get("Result", {}).get("StatusMessage", str(result))
            raise RuntimeError(f"ShareDev API 错误 StatusCode={status}: {msg}")

        return result.get("Value", result)

    def get_object_list(
        self,
        package_name: str = "CRM",
        include_system: bool = True,
        include_inactive: bool = True,
    ) -> list[dict]:
        """拉取租户对象列表"""
        path = "/EMDHFUNC/debugger/fx/findDescribeManageList"
        data = {
            "isIncludeFieldDescribe": False,
            "isIncludeSystemObj": include_system,
            "isIncludeUnActived": include_inactive,
            "packageName": package_name,
            "sourceInfo": "function",
            "serviceContext": {},
        }
        out = self._request(path, data)
        return out.get("objectDescribeList", [])

    def get_object_describe(
        self,
        api_name: str,
    ) -> dict:
        """拉取单个对象的字段描述"""
        path = "/EMDHFUNC/debugger/fx/findDescribeByApiName"
        data = {
            "describe_apiname": api_name,
            "get_label_direct": True,
            "include_buttons": False,
            "include_layout": False,
            "include_related_list": False,
            "include_describe_extra": False,
            "layout_type": "detail",
            "include_fields_extra": False,
            "check_cross_filter": False,
            "serviceContext": {},
        }
        out = self._request(path, data)
        return out.get("objectDescribe", {})

    def get_func_list(self, page_size: int = 3000, page_number: int = 1) -> list[dict]:
        """拉取 APL 函数列表（含 body 代码）"""
        path = "/EMDHFUNC/biz/query"
        data = {"pageSize": page_size, "pageNumber": page_number}
        out = self._request(path, data)
        return out.get("function", [])

    def get_func_by_api_names(self, api_names: list[str]) -> list[dict]:
        """按 api_name 批量查询函数详情（含 body）"""
        if not api_names:
            return []
        path = "/EMDHFUNC/biz/batchQuery"
        data = {"apiNames": api_names}
        out = self._request(path, data)
        return out.get("function", [])

    def update_func_body(
        self,
        api_name: str,
        body: str,
        commit_log: str = "",
        binding_object_api_name: Optional[str] = None,
    ) -> dict:
        """更新单个函数 body，需先拉取远程函数再合并 body"""
        remote_list = self.get_func_by_api_names([api_name])
        if not remote_list:
            raise ValueError(f"未找到函数: {api_name}")
        func = dict(remote_list[0])
        func["body"] = body
        if binding_object_api_name is not None:
            func["binding_object_api_name"] = binding_object_api_name
        path = "/EMDHFUNC/biz/updateBody"
        data = {"function": func, "token": ""}
        return self._request(path, data)

    def create_func(
        self,
        code_name: str,
        body: str,
        name_space: str = "flow",
        binding_object_api_name: str = "NONE",
        binding_object_label: str = "--",
        return_type: str = "void",
        func_type: str = "function",
    ) -> dict:
        """新建 APL 函数。name_space: flow|button|apl_controller|controller|library|erpdss-class 等"""
        path = "/EMDHFUNC/biz/create"
        func_data = {
            "function_name": code_name,
            "body": body,
            "name_space": name_space,
            "binding_object_api_name": binding_object_api_name,
            "binding_object_label": binding_object_label,
            "return_type": return_type,
            "type": func_type,
            "is_active": True,
            "status": "not_used",
            "package_name": "fx.custom.apl.script",
            "lang": 0,
            "is_control": False,
            "parameters": [],
        }
        data = {"function": func_data, "token": ""}
        return self._request(path, data)

    def batch_update_func_bodies(
        self,
        func_list: list[dict],
        commit_log: str = "sharedev push",
    ) -> dict:
        """批量更新函数 body，func_list 每项需含 api_name、body，其他字段可从 get_func_by_api_names 补全"""
        if not func_list:
            return {}
        api_names = [f.get("api_name") for f in func_list if f.get("api_name")]
        if not api_names:
            raise ValueError("func_list 需包含 api_name")
        remote_map = {f["api_name"]: f for f in self.get_func_by_api_names(api_names)}
        merged = []
        for f in func_list:
            api = f.get("api_name")
            if not api or api not in remote_map:
                continue
            item = dict(remote_map[api])
            item["body"] = f.get("body", item.get("body", ""))
            merged.append(item)
        if not merged:
            raise ValueError("无有效函数可更新")
        path = "/EMDHFUNC/biz/batchUpdateBody"
        data = {"functionList": merged, "commitLog": commit_log, "token": ""}
        return self._request(path, data)


def _load_session_cookies(session_path: Path) -> list[dict[str, Any]]:
    """从 deployer/session_*.json 读取 cookies。兼容旧格式。"""
    if not session_path.exists():
        raise FileNotFoundError(f"Session 文件不存在: {session_path}")
    data = json.loads(session_path.read_text(encoding="utf-8"))
    cookies = data.get("cookies", data) if isinstance(data, dict) else data
    if not isinstance(cookies, list):
        raise ValueError(f"Session 文件格式无效: {session_path}")
    return cookies


def _pick_cookie(cookies: list[dict[str, Any]], name: str) -> str:
    for cookie in cookies:
        if (cookie.get("name") or "") == name:
            return (cookie.get("value") or "").strip()
    return ""


def _extract_apl_header_value(body: str, key: str) -> str:
    pattern = rf"@{re.escape(key)}\s+(.+)"
    m = re.search(pattern, body or "", flags=re.IGNORECASE)
    return (m.group(1).strip() if m else "")


class ShareDevRuntimeClient:
    """基于 Web Session 调用运行/编译调试接口（不走开发者证书）。"""

    def __init__(
        self,
        domain: str,
        cookies: list[dict[str, Any]],
        *,
        referer: Optional[str] = None,
    ):
        self.domain = domain.rstrip("/")
        self.cookies = cookies
        self.fs_token = _pick_cookie(cookies, "fs_token")
        if not self.fs_token:
            raise ValueError("Session 中缺少 fs_token，无法调用 runtime/debug")
        self.referer = referer or f"{self.domain}/XV/UI/manage"
        self._session = requests.Session()
        for cookie in cookies:
            name = (cookie.get("name") or "").strip()
            value = cookie.get("value")
            if not name or value is None:
                continue
            self._session.cookies.set(
                name,
                value,
                domain=cookie.get("domain"),
                path=cookie.get("path") or "/",
            )
        self._session.headers.update(
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json; charset=UTF-8",
                "Origin": self.domain,
                "Referer": self.referer,
                "X-Requested-With": "XMLHttpRequest",
            }
        )

    def _post_web_api(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        trace_id: str = "",
    ) -> dict[str, Any]:
        trace = trace_id.strip() or f"E-E.local.1001-{int(time.time() * 1000)}"
        url = f"{self.domain}/FHH{path}"
        resp = self._session.post(
            url,
            params={"_fs_token": self.fs_token, "traceId": trace},
            headers={"x-trace-id": f"local_{uuid.uuid4().hex[:16]}"},
            json=payload,
            timeout=90,
        )
        resp.raise_for_status()
        return resp.json()

    @classmethod
    def from_config(
        cls,
        project_root: Optional[Path] = None,
        project_name: Optional[str] = None,
        cfg: Optional[dict[str, Any]] = None,
    ) -> "ShareDevRuntimeClient":
        if cfg is None:
            from utils import load_config

            cfg = load_config(None)
        fx = cfg.get("fxiaoke") or {}
        project = (project_name or fx.get("project_name") or "").strip()
        from deployer.deploy_login import get_session_path

        session_cfg = {"fxiaoke": dict(fx)}
        if project:
            session_cfg["fxiaoke"]["project_name"] = project
        session_path = get_session_path(session_cfg)
        cookies = _load_session_cookies(session_path)
        domain = (fx.get("base_url") or fx.get("sharedev_domain") or "https://www.fxiaoke.com").strip()
        if not domain.startswith("http"):
            domain = "https://" + domain.lstrip("/")
        return cls(domain, cookies)

    def runtime_debug(
        self,
        *,
        api_name: str,
        binding_object_api_name: str,
        function: dict[str, Any],
        data_source: str = "",
        input_data: Optional[list[Any]] = None,
        trace_id: str = "",
        token: str = "",
    ) -> dict[str, Any]:
        """调用系统运行/调试接口，返回原始 JSON。"""
        if not api_name.strip():
            raise ValueError("api_name 不能为空")
        if not binding_object_api_name.strip():
            raise ValueError("binding_object_api_name 不能为空")
        payload = {
            "api_name": api_name.strip(),
            "binding_object_api_name": binding_object_api_name.strip(),
            "input_data": input_data or [],
            "function": function,
            "data_source": data_source or "",
            "token": token or "",
        }
        return self._post_web_api("/EM1HFUNC/runtime/debug", payload, trace_id=trace_id)

    def build_function_payload(
        self,
        *,
        api_name: str,
        body: str,
        binding_object_api_name: str,
        function_name: str = "",
        binding_object_label: str = "",
        name_space: str = "flow",
        return_type: str = "void",
        commit_log: str = "1",
        existing_function: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """按 runtime/debug 所需结构构造 function 字段。"""
        function_name = function_name.strip() or _extract_apl_header_value(body, "codeName") or api_name
        binding_object_label = (
            binding_object_label.strip()
            or _extract_apl_header_value(body, "bindingObjectLabel")
            or "--"
        )
        description = _extract_apl_header_value(body, "description") or function_name
        if existing_function:
            func = dict(existing_function)
            func["body"] = body
            func["function_name"] = function_name
            func["binding_object_api_name"] = binding_object_api_name
            if binding_object_label:
                func["binding_object_label"] = binding_object_label
            return func
        return {
            "function_name": function_name,
            "api_name": api_name,
            "type": "function",
            "parameters": [],
            "body": body,
            "return_type": return_type,
            "binding_object_api_name": binding_object_api_name,
            "binding_object_label": binding_object_label,
            "application": "",
            "name_space": name_space,
            "version": 1,
            "is_active": True,
            "status": "not_used",
            "lang": 0,
            "remark": description,
            "class_name": "",
            "package_name": "fx.custom.apl.script",
            "commit_log": commit_log,
            "data_source": "",
            "is_control": False,
        }

    def create_function(
        self,
        *,
        function: dict[str, Any],
        token: str = "",
        trace_id: str = "",
    ) -> dict[str, Any]:
        payload = {"function": function, "token": token or f"{time.time():.16f}"}
        return self._post_web_api("/EM1HFUNC/biz/create", payload, trace_id=trace_id)


def fetch_objects(project_root: Optional[Path] = None) -> list[dict]:
    """拉取对象列表。"""
    domain, cert = load_sharedev_config(project_root)
    client = ShareDevClient(domain, cert)
    return client.get_object_list()


def fetch_functions(project_root: Optional[Path] = None) -> list[dict]:
    """拉取函数列表。"""
    domain, cert = load_sharedev_config(project_root)
    client = ShareDevClient(domain, cert)
    return client.get_func_list()


def fetch_object_describe(
    api_name: str,
    project_root: Optional[Path] = None,
    project_name: Optional[str] = None,
) -> dict:
    """拉取对象字段描述。"""
    domain, cert = load_sharedev_config(project_root, project_name)
    client = ShareDevClient(domain, cert)
    return client.get_object_describe(api_name)


def push_func(
    api_name: str,
    body: str,
    commit_log: str = "sharedev push",
    project_root: Optional[Path] = None,
    project_name: Optional[str] = None,
) -> dict:
    """推送单个函数 body。"""
    domain, cert = load_sharedev_config(project_root, project_name)
    client = ShareDevClient(domain, cert)
    return client.update_func_body(api_name, body, commit_log)


def runtime_debug_func(
    *,
    api_name: str,
    body: str,
    binding_object_api_name: str,
    project_root: Optional[Path] = None,
    project_name: Optional[str] = None,
    cfg: Optional[dict[str, Any]] = None,
    data_source: str = "",
    function_name: str = "",
    binding_object_label: str = "",
    name_space: str = "flow",
    return_type: str = "void",
    existing_function: Optional[dict[str, Any]] = None,
) -> dict:
    """使用当前项目 Session 调 runtime/debug（旁路能力，不影响原主流程）。"""
    client = ShareDevRuntimeClient.from_config(project_root, project_name, cfg=cfg)
    function = client.build_function_payload(
        api_name=api_name,
        body=body,
        binding_object_api_name=binding_object_api_name,
        function_name=function_name,
        binding_object_label=binding_object_label,
        name_space=name_space,
        return_type=return_type,
        existing_function=existing_function,
    )
    return client.runtime_debug(
        api_name=api_name,
        binding_object_api_name=binding_object_api_name,
        function=function,
        data_source=data_source,
        input_data=[],
    )


def web_create_func(
    *,
    api_name: str,
    body: str,
    binding_object_api_name: str,
    project_root: Optional[Path] = None,
    project_name: Optional[str] = None,
    cfg: Optional[dict[str, Any]] = None,
    function_name: str = "",
    binding_object_label: str = "",
    name_space: str = "flow",
    return_type: str = "void",
) -> dict:
    """使用当前项目 Session 直连创建函数。"""
    client = ShareDevRuntimeClient.from_config(project_root, project_name, cfg=cfg)
    function = client.build_function_payload(
        api_name=api_name,
        body=body,
        binding_object_api_name=binding_object_api_name,
        function_name=function_name,
        binding_object_label=binding_object_label,
        name_space=name_space,
        return_type=return_type,
    )
    return client.create_function(function=function)


def web_create_success(result: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    value = (result or {}).get("Value") or {}
    func = value.get("function") or {}
    ok = bool(func.get("id") and func.get("api_name"))
    return ok, func


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ShareDev 证书：拉取/推送对象、函数")
    parser.add_argument("--objects", action="store_true", help="拉取对象列表")
    parser.add_argument("--functions", action="store_true", help="拉取函数列表")
    parser.add_argument("--describe", type=str, metavar="API_NAME", help="拉取对象描述")
    parser.add_argument("--push", type=str, metavar="API_NAME", help="推送函数（需配合 --file 指定 .apl 文件）")
    parser.add_argument("--runtime-debug", type=str, metavar="API_NAME",
                        help="调用 Web Session runtime/debug 接口（需配合 --file 和 --binding-object-api）")
    parser.add_argument("--web-create", type=str, metavar="API_NAME",
                        help="调用 Web Session biz/create 接口新建函数（需配合 --file 和 --binding-object-api）")
    parser.add_argument("--file", "-f", type=str, help=".apl 文件路径（用于 --push）")
    parser.add_argument("--binding-object-api", type=str, default="", help="runtime/debug 所需绑定对象 API")
    parser.add_argument("--binding-object-label", type=str, default="", help="runtime/debug 所需绑定对象中文名（可选）")
    parser.add_argument("--data-source", type=str, default="", help="runtime/debug 所需数据源 ID（可选）")
    parser.add_argument("--function-name", type=str, default="", help="runtime/debug 所需函数名称（可选）")
    parser.add_argument("--namespace", type=str, default="flow", help="runtime/debug 所需命名空间，默认 flow")
    parser.add_argument("--return-type", type=str, default="void", help="runtime/debug 所需返回类型，默认 void")
    parser.add_argument("--commit", type=str, default="sharedev push", help="推送时的版本说明")
    parser.add_argument("--output", "-o", type=str, help="输出文件（JSON）")
    parser.add_argument("--project", "-p", type=str, help="项目名，多项目时按项目分目录存储（默认从 config 读取）")
    parser.add_argument("--config", type=str, default=None, help="config 文件路径")
    args = parser.parse_args()

    root = Path.cwd()
    if not any([args.objects, args.functions, args.describe, args.push, args.runtime_debug, args.web_create]):
        parser.print_help()
        exit(1)

    project = (args.project or "").strip()
    if not project:
        try:
            from utils import load_config
            cfg = load_config(args.config)
            project = (cfg.get("fxiaoke") or {}).get("project_name", "").strip() or "default"
        except Exception:
            project = "default"

    def _out_path(kind: str) -> Path:
        if args.output:
            return Path(args.output)
        out_dir = _TOOLS / "sharedev_pull" / project
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / f"{kind}.json"

    try:
        if args.objects:
            domain, cert = load_sharedev_config(root, project or None)
            client = ShareDevClient(domain, cert)
            data = client.get_object_list()
            print(f"对象数量: {len(data)} (项目: {project})")
            out = _out_path("objects")
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  已保存: {out}")
            if not args.output:
                for o in data[:20]:
                    print(f"  {o.get('api_name')} - {o.get('display_name')}")
        elif args.functions:
            domain, cert = load_sharedev_config(root, project or None)
            client = ShareDevClient(domain, cert)
            data = client.get_func_list()
            print(f"函数数量: {len(data)} (项目: {project})")
            out = _out_path("functions")
            out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  已保存: {out}")
            if not args.output:
                for f in data[:20]:
                    print(f"  {f.get('api_name')} - {f.get('code_name')}")
        elif args.describe:
            data = fetch_object_describe(args.describe, root, project or None)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            if args.output:
                Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        elif args.push:
            if not args.file:
                print("错误: --push 需配合 --file 指定 .apl 文件")
                exit(1)
            body = Path(args.file).read_text(encoding="utf-8")
            data = push_func(args.push, body, args.commit, root, project or None)
            print(f"推送成功: {args.push}")
        elif args.runtime_debug:
            if not args.file:
                print("错误: --runtime-debug 需配合 --file 指定 .apl 文件")
                exit(1)
            if not args.binding_object_api:
                print("错误: --runtime-debug 需配合 --binding-object-api")
                exit(1)
            body = Path(args.file).read_text(encoding="utf-8")
            result = runtime_debug_func(
                api_name=args.runtime_debug,
                body=body,
                binding_object_api_name=args.binding_object_api,
                project_root=root,
                project_name=project or None,
                data_source=args.data_source,
                function_name=args.function_name,
                binding_object_label=args.binding_object_label,
                name_space=args.namespace,
                return_type=args.return_type,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.web_create:
            if not args.file:
                print("错误: --web-create 需配合 --file 指定 .apl 文件")
                exit(1)
            if not args.binding_object_api:
                print("错误: --web-create 需配合 --binding-object-api")
                exit(1)
            body = Path(args.file).read_text(encoding="utf-8")
            result = web_create_func(
                api_name=args.web_create,
                body=body,
                binding_object_api_name=args.binding_object_api,
                project_root=root,
                project_name=project or None,
                cfg=cfg if 'cfg' in locals() else None,
                function_name=args.function_name,
                binding_object_label=args.binding_object_label,
                name_space=args.namespace,
                return_type=args.return_type,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"错误: {e}")
        exit(1)
