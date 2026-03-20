#!/usr/bin/env python3
"""
更新 config.local.yml 中的纷享销客账号密码。
用法：python3 set_credentials.py --username 18800001111 --password mypass123
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description="配置纷享销客登录凭证")
    parser.add_argument("--username", "-u", required=True, help="账号（手机号或邮箱）")
    parser.add_argument("--password", "-p", required=True, help="密码")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.local.yml"),
        help="配置文件路径（默认：config.local.yml）",
    )
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"❌ 配置文件不存在: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if "fxiaoke" not in cfg:
        cfg["fxiaoke"] = {}

    old_user = cfg["fxiaoke"].get("username", "")
    cfg["fxiaoke"]["username"] = args.username
    cfg["fxiaoke"]["password"] = args.password

    cfg_path.write_text(
        yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    if old_user and old_user != args.username:
        print(f"✅ 账号已从 {old_user} 切换为 {args.username}")
    else:
        print(f"✅ 账号已配置: {args.username}")

    # 同时删除旧 session，强制重新登录（含按项目分存的 session_*.json）
    deployer_dir = Path(__file__).parent / "deployer"
    for f in deployer_dir.glob("session*.json"):
        f.unlink()
        print(f"🔄 已清除 session: {f.name}")


if __name__ == "__main__":
    main()
