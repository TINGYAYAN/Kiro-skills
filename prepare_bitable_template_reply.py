from __future__ import annotations

import argparse

from feishu_record import (
    build_bitable_template_reply,
    create_bitable_template_table,
    get_fixed_bitable_template_info,
)
from utils import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="输出可直接回复给用户的批量模板文案；默认优先使用固定模板链接")
    parser.add_argument("--name", default="APL批量生成模板", help="新建数据表名称")
    parser.add_argument("--no-examples", action="store_true", help="只建空表头，不写示例行")
    parser.add_argument("--create", action="store_true", help="显式创建新模板表；默认优先使用配置中的固定模板链接")
    parser.add_argument("--config", default=None, help="配置文件路径")
    args = parser.parse_args()

    cfg = load_config(args.config)
    fixed_info = get_fixed_bitable_template_info(cfg)
    if fixed_info.get("is_fixed") and not args.create:
        info = fixed_info
    else:
        info = create_bitable_template_table(
            cfg,
            table_name=args.name,
            with_examples=not args.no_examples,
        )
    print(build_bitable_template_reply(info))


if __name__ == "__main__":
    main()
