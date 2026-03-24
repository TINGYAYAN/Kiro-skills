#!/usr/bin/env python3
"""
输出当前项目的对象和函数数量。从 sharedev_pull/{project}/ 读取，若无则执行拉取。
用法: python3 count_objects_functions.py [项目名]
项目名默认从 config.local.yml 的 fxiaoke.project_name 读取。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).parent
PULL_DIR = TOOLS / "sharedev_pull"


def main():
    project = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not project:
        try:
            import yaml
            cfg = yaml.safe_load((TOOLS / "config.local.yml").read_text(encoding="utf-8")) or {}
            project = (cfg.get("fxiaoke") or {}).get("project_name", "").strip()
        except Exception:
            pass
    if not project:
        print("无法确定项目名，请传入: python3 count_objects_functions.py <项目名>", file=sys.stderr)
        sys.exit(1)

    obj_path = PULL_DIR / project / "objects.json"
    func_path = PULL_DIR / project / "functions.json"

    if not obj_path.exists() or not func_path.exists():
        r = subprocess.run(
            ["bash", str(TOOLS / "pull_project_sharedev.sh"), project],
            cwd=TOOLS,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode != 0:
            print(f"拉取失败: {out}", file=sys.stderr)
            sys.exit(1)
        obj_path = PULL_DIR / project / "objects.json"
        func_path = PULL_DIR / project / "functions.json"

    if not obj_path.exists() or not func_path.exists():
        print(f"sharedev_pull/{project}/ 下无 objects.json 或 functions.json", file=sys.stderr)
        sys.exit(1)

    objs = json.loads(obj_path.read_text(encoding="utf-8"))
    funcs = json.loads(func_path.read_text(encoding="utf-8"))
    n_obj = len(objs) if isinstance(objs, list) else 0
    n_func = len(funcs) if isinstance(funcs, list) else 0

    print(f"当前租户有 {n_obj} 个对象、{n_func} 个函数，已全部拉取对象 apiname 和函数内容。请问要新建/更新什么函数需求？")


if __name__ == "__main__":
    main()
