from __future__ import annotations

import argparse

from feishu_record import create_bitable_template_table
from utils import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="在当前飞书多维表格 base 下创建 APL 批量生成模板表")
    parser.add_argument("--name", default="APL批量生成模板", help="新建数据表名称")
    parser.add_argument("--no-examples", action="store_true", help="只建空表头，不写示例行")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args()

    cfg = load_config(args.config)
    result = create_bitable_template_table(
        cfg,
        table_name=args.name,
        with_examples=not args.no_examples,
    )

    print("模板表创建成功")
    print(f"表名: {result['table_name']}")
    print(f"table_id: {result['table_id']}")
    print(f"示例行: {result['created_records']}")
    print(f"链接: {result['url']}")


if __name__ == "__main__":
    main()
