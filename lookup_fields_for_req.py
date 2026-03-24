#!/usr/bin/env python3
"""
从 ShareDev 拉取对象字段，输出 对象->字段(label: api) 映射，供 req.yml 确认。
用法: python3 lookup_fields_for_req.py <项目名> <object_api1> [object_api2] ...
输出 YAML 格式，需求中提到的字段（如日期、打款金额、近一个季度回款）会优先列出。
"""
from __future__ import annotations

import sys
import yaml
from pathlib import Path

TOOLS = Path(__file__).parent
sys.path.insert(0, str(TOOLS))
from utils import load_config


def main():
    if len(sys.argv) < 3:
        print("用法: python3 lookup_fields_for_req.py <项目名> <object_api1> [object_api2] ...", file=sys.stderr)
        sys.exit(1)

    project = sys.argv[1].strip()
    object_apis = [a.strip() for a in sys.argv[2:] if a.strip()]

    cfg = load_config()
    cfg.setdefault("fxiaoke", {})["project_name"] = project

    # 对象 api -> 中文标签（从 objects.json）
    obj_path = TOOLS / "sharedev_pull" / project / "objects.json"
    api_to_label = {}
    if obj_path.exists():
        import json
        objs = json.loads(obj_path.read_text(encoding="utf-8"))
        for o in objs:
            if isinstance(o, dict):
                api = o.get("api_name", "")
                label = o.get("display_name", "")
                if api:
                    api_to_label[api] = label

    from fetcher.fetch_fields import fetch_fields

    result = {}
    for obj_api in object_apis:
        label = api_to_label.get(obj_api, obj_api)
        fields = fetch_fields(obj_api, label, cfg, project_name=project, force_refresh=False)
        if fields:
            result[f"{label}({obj_api})"] = {f["label"]: f["api"] for f in fields}
        else:
            result[f"{label}({obj_api})"] = "# 未拉到字段，请检查证书"

    text = yaml.dump(result, allow_unicode=True)
    print(text)

    out_path = TOOLS / "sharedev_pull" / project / "field_mappings.yml"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"# 已保存到 sharedev_pull/{project}/field_mappings.yml", file=sys.stderr)


if __name__ == "__main__":
    main()
