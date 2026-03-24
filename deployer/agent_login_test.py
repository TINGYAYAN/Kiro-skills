"""
测试代理登录 API：调用 GetAdminAgentLoginToken 并打印响应

用法：
  python -m deployer.agent_login_test --employee-id 1001

需要：已有 session 文件（deployer/session_*.json），即至少成功登录过并保存了 cookies。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_TOOLS = Path(__file__).parent.parent
sys.path.insert(0, str(_TOOLS))

from utils import load_config


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--employee-id", default="1001", help="员工 ID")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    from deployer.deploy_login import get_session_path

    path = get_session_path(cfg)
    if not path.exists():
        print(f"错误: 未找到 session 文件 {path}，请先执行一次部署完成登录")
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    cookies = data.get("cookies", data) if isinstance(data, dict) else data
    if not cookies:
        print("错误: session 文件中无 cookies")
        sys.exit(1)

    base_url = cfg["fxiaoke"].get("base_url", "https://www.fxiaoke.com").rstrip("/")
    from deployer.agent_login import get_agent_login_url

    url = get_agent_login_url(cookies, args.employee_id, base_url)
    if url:
        print(f"成功! SSOLogin URL:\n{url}")
    else:
        print("失败: 未获取到 token。可能需要检查 API 响应格式，请用 curl 抓包查看返回字段。")
        # 尝试直接调用看原始响应
        import requests
        from deployer.agent_login import _cookies_to_jar
        jar, fs_token = _cookies_to_jar(cookies)
        r = requests.post(
            f"{base_url}/FHH/EM1HNCRM/API/v1/object/personnelrest/service/GetAdminAgentLoginToken",
            params={"_fs_token": fs_token or "x", "traceId": f"test-{id(cookies)}"},
            headers={"content-type": "application/json", "accept": "application/json"},
            cookies=jar,
            json={"employeeId": args.employee_id},
            timeout=15,
        )
        print(f"HTTP {r.status_code}")
        try:
            print("Response:", json.dumps(r.json(), indent=2, ensure_ascii=False))
        except Exception:
            print("Response:", r.text[:500])


if __name__ == "__main__":
    main()
