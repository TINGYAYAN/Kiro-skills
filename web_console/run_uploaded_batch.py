from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "web_console" / "runtime"
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行工作台上传的批量模板")
    parser.add_argument("--config", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--project", default="")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--web-create-api", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[upload-batch] 模板文件不存在: {csv_path}")
        return 1

    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cleaned = {str(k or "").strip(): str(v or "").strip() for k, v in row.items()}
            if not (cleaned.get("描述") or "").strip():
                continue
            project = (args.project or cleaned.get("项目") or "").strip()
            if args.project and project != args.project:
                continue
            rows.append(
                {
                    "project": project,
                    "requirement": cleaned.get("描述", "").strip(),
                    "object_api": cleaned.get("绑定对象API", "").strip(),
                    "object_label": cleaned.get("绑定对象", "").strip(),
                    "function_type": cleaned.get("函数类型", "").strip() or "流程函数",
                    "code_name": cleaned.get("函数名", "").strip(),
                    "description": cleaned.get("描述", "").strip()[:100],
                }
            )

    print(f"[upload-batch] 待处理记录数: {len(rows)}")
    if not rows:
        return 0

    success = 0
    failed = 0
    for idx, req in enumerate(rows, start=1):
        req_file = RUNTIME_DIR / f"upload_req_{idx}_{uuid.uuid4().hex[:8]}.yml"
        req_file.write_text(yaml.safe_dump(req, allow_unicode=True, sort_keys=False), encoding="utf-8")
        cmd = [
            sys.executable,
            str(ROOT / "pipeline.py"),
            "--config",
            args.config,
            "--req",
            str(req_file),
            "--step",
            "deploy",
            "--runtime-precheck",
            "--no-feishu-log",
        ]
        if args.web_create_api:
            cmd.append("--web-create-api")
        if args.no_notify:
            cmd.append("--no-notify")
        if req.get("project"):
            cmd.extend(["--project", req["project"]])

        print(f"\n[upload-batch] 第 {idx}/{len(rows)} 条: {req.get('code_name') or req.get('requirement')[:24]}")
        print(f"[upload-batch] 项目: {req.get('project') or '-'} | 对象: {req.get('object_label') or req.get('object_api') or '-'}")
        proc = subprocess.run(cmd, cwd=str(ROOT))
        if proc.returncode == 0:
            success += 1
        else:
            failed += 1
            print(f"[upload-batch] 第 {idx} 条失败，继续下一条")

    print("\n[upload-batch] 执行完成")
    print(json.dumps({"total": len(rows), "success": success, "failed": failed}, ensure_ascii=False))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
