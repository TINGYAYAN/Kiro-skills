"""
RAG 检索模块（可复用于生成器等）

用法：
  from rag import get_retriever, retrieve_apl_examples

  # 通用检索
  retriever = get_retriever("apl_examples", cfg)
  docs = retriever.search("根据组织机构代码关联客户", k=3)

  # 生成器专用
  examples = retrieve_apl_examples(requirement, function_type, cfg, num=6)

重建索引（新增 APL 文件后）：
  python -m rag.rebuild_index
"""
from rag.retriever import RAGRetriever, get_retriever
from rag.apl_examples import retrieve_apl_examples, build_apl_index

__all__ = ["RAGRetriever", "get_retriever", "retrieve_apl_examples", "build_apl_index"]
