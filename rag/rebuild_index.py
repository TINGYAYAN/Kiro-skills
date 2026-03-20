#!/usr/bin/env python3
"""重建 APL 示例 RAG 索引（新增/修改 APL 文件后执行）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import load_config
from rag.apl_examples import build_apl_index


def main():
    cfg = load_config()
    n = build_apl_index(cfg)
    print(f"[RAG] 索引已重建，共 {n} 个 APL 示例")


if __name__ == "__main__":
    main()
