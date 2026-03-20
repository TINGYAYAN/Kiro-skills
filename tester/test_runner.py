"""
APL 函数自动化测试执行器

用法：
  python test_runner.py --case cases/example_申领T2经销商.yml
  python test_runner.py --case cases/example_申领T2经销商.yml --no-teardown   # 失败时保留测试数据
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from tester.openapi_client import FxOpenAPIClient, get_client
from utils import load_config

REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ------------------------------------------------------------------ #
# 上下文：保存各阶段创建记录的引用
# ------------------------------------------------------------------ #

class RunContext:
    def __init__(self):
        self.refs = {}  # type: dict  # "stage.id" -> record dict

    def save(self, stage: str, step_id: str, record: dict):
        key = f"{stage}.{step_id}"
        self.refs[key] = record
        print(f"  [ctx] 保存引用 {key} = {record.get('_id', record)}")

    def resolve(self, ref: str) -> Optional[dict]:
        return self.refs.get(ref)

    def resolve_id(self, ref: str) -> Optional[str]:
        r = self.resolve(ref)
        return r.get("_id") if r else None

    def interpolate(self, value: Any) -> Any:
        """将字符串中的 {{stage.id._field}} 替换为实际值。"""
        if not isinstance(value, str):
            return value
        import re
        def replacer(m):
            parts = m.group(1).strip().split(".")
            if len(parts) >= 2:
                key = f"{parts[0]}.{parts[1]}"
                rec = self.refs.get(key)
                if rec and len(parts) == 3:
                    return str(rec.get(parts[2], ""))
                if rec:
                    return str(rec.get("_id", ""))
            return m.group(0)
        return re.sub(r"\{\{(.+?)\}\}", replacer, value)


# ------------------------------------------------------------------ #
# 步骤执行
# ------------------------------------------------------------------ #

def execute_step(client: FxOpenAPIClient, step: dict, stage: str, ctx: RunContext):
    action = step["action"]
    obj = step["object"]
    step_id = step.get("id", f"{stage}_{action}")

    if action == "create":
        raw_data = step.get("data", {})
        data = {k: ctx.interpolate(v) for k, v in raw_data.items()}
        record = client.create(obj, data)
        print(f"  [{stage}] 创建 {obj}: {record.get('_id')}")
        ctx.save(stage, step_id, record)

    elif action == "update":
        record_id = _resolve_record_id(step, ctx)
        raw_data = step.get("data", {})
        data = {k: ctx.interpolate(v) for k, v in raw_data.items()}
        client.update(obj, record_id, data)
        print(f"  [{stage}] 更新 {obj}: {record_id}")

    elif action == "delete":
        record_id = _resolve_record_id(step, ctx)
        if record_id:
            client.delete(obj, record_id)
            print(f"  [{stage}] 删除 {obj}: {record_id}")
        else:
            print(f"  [{stage}] 跳过删除（无记录ID）")

    elif action == "find":
        filters_raw = step.get("filters", [])
        filters = [{**f, "field_values": [ctx.interpolate(v) for v in f.get("field_values", [])]}
                   for f in filters_raw]
        results = client.find(obj, filters, step.get("columns"))
        record = results[0] if results else {}
        ctx.save(stage, step_id, record)
        print(f"  [{stage}] 查询 {obj}: 找到 {len(results)} 条")

    else:
        raise ValueError(f"未知 action: {action}")


def _resolve_record_id(step: dict, ctx: RunContext) -> Optional[str]:
    if "id_value" in step:
        return ctx.interpolate(step["id_value"])
    if "record_ref" in step:
        return ctx.resolve_id(step["record_ref"])
    return None


# ------------------------------------------------------------------ #
# 断言
# ------------------------------------------------------------------ #

class AssertionError_(Exception):
    pass


def check_assertion(client: FxOpenAPIClient, assertion: dict, ctx: RunContext,
                    poll_retries: int, poll_interval: float) -> Tuple[bool, str]:
    obj = assertion["object"]
    field = assertion["field"]
    operator = assertion.get("operator", "eq")
    expected = ctx.interpolate(str(assertion.get("expected", "")))
    description = assertion.get("description", f"{obj}.{field} {operator} {expected}")

    record_id = _resolve_record_id(assertion, ctx)
    if not record_id:
        return False, f"无法解析记录 ID：{assertion.get('record_ref')}"

    for attempt in range(1, poll_retries + 1):
        record = client.find_by_id(obj, record_id, [field])
        actual = str(record.get(field, "")) if record else ""

        if _compare(actual, operator, expected):
            return True, f"PASS: {description} (actual={actual})"

        if attempt < poll_retries:
            print(f"  [断言] 等待 {poll_interval}s，第 {attempt}/{poll_retries} 次... actual={actual}")
            time.sleep(poll_interval)

    return False, f"FAIL: {description} | actual={actual} expected={expected}"


def _compare(actual: str, operator: str, expected: str) -> bool:
    if operator == "eq":
        return actual == expected
    elif operator == "not_null":
        return bool(actual)
    elif operator == "null":
        return not actual
    elif operator == "contains":
        return expected in actual
    elif operator == "not_eq":
        return actual != expected
    else:
        raise ValueError(f"不支持的 operator: {operator}")


# ------------------------------------------------------------------ #
# 单个用例执行
# ------------------------------------------------------------------ #

def run_case(client: FxOpenAPIClient, case: dict, cfg: dict,
             do_teardown: bool = True) -> dict:
    tester_cfg = cfg.get("tester", {})
    poll_retries = int(tester_cfg.get("poll_max_retries", 10))
    poll_interval = float(tester_cfg.get("poll_interval_seconds", 2))
    trigger_wait = float(tester_cfg.get("trigger_wait_seconds", 5))

    ctx = RunContext()
    results = {
        "function": case.get("function", "unknown"),
        "description": case.get("description", ""),
        "passed": 0,
        "failed": 0,
        "assertions": [],
        "errors": [],
    }

    # 1. Setup
    print("\n[测试] === setup ===")
    for step in case.get("setup", []):
        execute_step(client, step, "setup", ctx)

    # 2. Trigger
    print("[测试] === trigger ===")
    for step in case.get("trigger", []):
        execute_step(client, step, "trigger", ctx)

    # 等待函数执行
    print(f"[测试] 等待 {trigger_wait}s 函数执行...")
    time.sleep(trigger_wait)

    # 3. Assertions
    print("[测试] === assertions ===")
    for assertion in case.get("assertions", []):
        ok, msg = check_assertion(client, assertion, ctx, poll_retries, poll_interval)
        print(f"  {'✓' if ok else '✗'} {msg}")
        results["assertions"].append({"ok": ok, "message": msg})
        if ok:
            results["passed"] += 1
        else:
            results["failed"] += 1

    # 4. Teardown
    if do_teardown:
        print("[测试] === teardown ===")
        for step in reversed(case.get("teardown", [])):
            try:
                execute_step(client, step, "teardown", ctx)
            except Exception as e:
                print(f"  [警告] teardown 出错: {e}")

    return results


# ------------------------------------------------------------------ #
# 报告
# ------------------------------------------------------------------ #

def save_report(all_results: list, case_file: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": ts,
        "case_file": case_file,
        "summary": {
            "total_cases": len(all_results),
            "passed_cases": sum(1 for r in all_results if r["failed"] == 0),
            "total_assertions": sum(r["passed"] + r["failed"] for r in all_results),
            "passed_assertions": sum(r["passed"] for r in all_results),
        },
        "cases": all_results,
    }
    report_path = REPORTS_DIR / f"report_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # 打印摘要
    s = report["summary"]
    print(f"\n{'='*50}")
    print(f"测试报告: {report_path}")
    print(f"用例: {s['passed_cases']}/{s['total_cases']} 通过")
    print(f"断言: {s['passed_assertions']}/{s['total_assertions']} 通过")
    print('='*50)
    return report_path


# ------------------------------------------------------------------ #
# 主入口
# ------------------------------------------------------------------ #

def run(case_file: str, cfg: dict, do_teardown: bool = True) -> list:
    case_data = yaml.safe_load(Path(case_file).read_text(encoding="utf-8"))
    client = FxOpenAPIClient(cfg)

    all_results = []

    # 主用例
    print(f"\n[测试] 运行用例: {case_data.get('function', case_file)}")
    result = run_case(client, case_data, cfg, do_teardown)
    all_results.append(result)

    # extra_cases（附加场景）
    for extra in case_data.get("extra_cases", []):
        print(f"\n[测试] 运行附加场景: {extra.get('name', 'extra')}")
        # 合并主用例的 setup，允许复用
        merged = {**case_data, **extra}
        extra_result = run_case(client, merged, cfg, do_teardown)
        extra_result["function"] = extra.get("name", "extra")
        all_results.append(extra_result)

    save_report(all_results, case_file)
    return all_results


def main():
    parser = argparse.ArgumentParser(description="APL 函数自动化测试")
    parser.add_argument("--case", required=True, help="测试用例 YAML 文件路径")
    parser.add_argument("--no-teardown", dest="no_teardown", action="store_true",
                        help="测试后不清理数据（方便排查问题）")
    parser.add_argument("--config", default=None, help="config 文件路径")
    args = parser.parse_args()

    cfg = load_config(args.config)
    results = run(args.case, cfg, do_teardown=not args.no_teardown)

    failed = sum(r["failed"] for r in results)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
