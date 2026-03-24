#!/usr/bin/env python3
"""
新项目配置 + 拉取对象和函数，一气呵成。
用法: python3 setup_project_and_pull.py <项目名> <证书原文> <bootstrap_token_url>

从用户消息提取证书和 URL 后，写入 config、执行 sharedev 拉取，输出对象/函数数量供 bot 回复。
"""
from __future__ import annotations

import sys
import yaml
from pathlib import Path

TOOLS = Path(__file__).parent
CONFIG_PATH = TOOLS / "config.local.yml"


def main():
    if len(sys.argv) < 4:
        print("用法: python3 setup_project_and_pull.py <项目名> <证书> <bootstrap_url>", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1].strip()
    cert = sys.argv[2].strip()
    url = sys.argv[3].strip()

    if not project or not cert:
        print("项目名和证书必填", file=sys.stderr)
        sys.exit(1)

    # 读并合并 config
    cfg = {}
    if CONFIG_PATH.exists():
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}

    fx = cfg.setdefault("fxiaoke", {})
    fx["project_name"] = project
    fx["bootstrap_token_url"] = url
    projs = fx.setdefault("sharedev_projects", {})
    projs[project] = {"domain": "https://www.fxiaoke.com", "certificate": cert}
    CONFIG_PATH.write_text(yaml.dump(cfg, allow_unicode=True), encoding="utf-8")
    print(f"[setup] 已写入 config，项目: {project}")

    # 执行拉取
    import subprocess
    r = subprocess.run(
        [sys.executable, "-m", "fetcher.sharedev_client", "--objects", "--project", project],
        cwd=TOOLS,
        capture_output=True,
        text=True,
        timeout=60,
    )
    obj_out = r.stdout or ""
    obj_err = r.stderr or ""
    if r.returncode != 0:
        print(f"[setup] 对象拉取失败: {obj_err}", file=sys.stderr)
    else:
        print(obj_out, end="")

    r2 = subprocess.run(
        [sys.executable, "-m", "fetcher.sharedev_client", "--functions", "--project", project],
        cwd=TOOLS,
        capture_output=True,
        text=True,
        timeout=60,
    )
    func_out = r2.stdout or ""
    func_err = r2.stderr or ""
    if r2.returncode != 0:
        print(f"[setup] 函数拉取失败: {func_err}", file=sys.stderr)
    else:
        print(func_out, end="")

    # 解析数量
    obj_num = ""
    func_num = ""
    for line in (obj_out + obj_err).splitlines():
        if "对象数量:" in line:
            parts = line.split("对象数量:")[-1].strip().split()
            if parts:
                obj_num = parts[0]
            break
    for line in (func_out + func_err).splitlines():
        if "函数数量:" in line:
            parts = line.split("函数数量:")[-1].strip().split()
            if parts:
                func_num = parts[0]
            break

    print("\n--- 请将以下内容回复用户 ---")
    if obj_num and func_num:
        print(f"当前租户有 {obj_num} 个对象、{func_num} 个函数，已全部拉取对象 apiname 和函数内容。请问要新建/更新什么函数需求？")
    else:
        print("拉取完成，但未能解析数量。请检查上方输出。")


if __name__ == "__main__":
    main()
