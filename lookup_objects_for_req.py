#!/usr/bin/env python3
"""
从 sharedev_pull/{项目}/objects.json 查找需求中提到的对象的实际 api_name。
用法: python3 lookup_objects_for_req.py <项目名> [对象标签1] [对象标签2] ...
或: echo "银行流水 客户" | python3 lookup_objects_for_req.py 朗润生物
输出: label -> api_name 的 YAML，供 req.yml 使用。
"""
from __future__ import annotations

import json
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
        print("请传入项目名: python3 lookup_objects_for_req.py <项目名> 银行流水 客户", file=sys.stderr)
        sys.exit(1)

    obj_path = PULL_DIR / project / "objects.json"
    if not obj_path.exists():
        print(f"sharedev_pull/{project}/objects.json 不存在，请先拉取", file=sys.stderr)
        sys.exit(1)

    objs = json.loads(obj_path.read_text(encoding="utf-8"))
    label_to_api = {}
    for o in objs:
        if isinstance(o, dict):
            api = o.get("api_name", "")
            label = o.get("display_name", "")
            if api and label:
                label_to_api[label.strip()] = api

    # 输入：命令行参数或 stdin
    labels = []
    if len(sys.argv) > 2:
        labels = [a.strip() for a in sys.argv[2:] if a.strip()]
    if not labels:
        line = sys.stdin.readline()
        if line:
            labels = [s.strip() for s in line.split() if s.strip()]

    if not labels:
        print("请传入对象标签，如: 银行流水 客户", file=sys.stderr)
        sys.exit(1)

    found = {}
    for lbl in labels:
        if lbl in label_to_api:
            found[lbl] = label_to_api[lbl]
        else:
            for k, v in label_to_api.items():
                if lbl in k or k in lbl:
                    found[lbl] = v
                    break
            if lbl not in found:
                found[lbl] = f"# 未找到，请在 objects.json 中确认"

    out_lines = [f"  {lbl}: {api}" for lbl, api in found.items()]
    for line in out_lines:
        print(line)

    out_path = PULL_DIR / project / "objects_lookup.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import yaml
    out_path.write_text(yaml.dump(dict(found), allow_unicode=True), encoding="utf-8")
    print(f"\n# 已保存到 {out_path.relative_to(TOOLS)}", file=sys.stderr)


if __name__ == "__main__":
    main()
