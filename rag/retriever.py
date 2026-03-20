"""
通用 RAG 检索器，基于 ChromaDB 向量存储。

支持多 collection，可复用于 APL 示例、CRM schema 等语义检索场景。
"""
from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

INDEX_DIR = _TOOLS / ".rag_index"


def _get_embedding_function(cfg: dict):
    import chromadb.utils.embedding_functions as ef

    llm = cfg.get("llm") or {}
    rag_cfg = cfg.get("rag") or {}
    import os
    api_key = (
        rag_cfg.get("api_key")
        or llm.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    model = rag_cfg.get("embedding_model") or "text-embedding-3-small"
    base_url = rag_cfg.get("base_url") or llm.get("base_url")

    kwargs = {"model_name": model}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        base = base_url.rstrip("/")
        kwargs["api_base"] = base + "/v1" if not base.endswith("/v1") else base
    return ef.OpenAIEmbeddingFunction(**kwargs)


class RAGRetriever:
    def __init__(self, collection_name: str, cfg: dict, persist_dir: Path | None = None):
        self.collection_name = collection_name
        self.cfg = cfg
        self.persist_dir = persist_dir or (INDEX_DIR / collection_name)
        self._client = None
        self._collection = None

    def _ensure_client(self):
        if self._client is not None:
            return
        import chromadb
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        ef = _get_embedding_function(self.cfg)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )

    def add_documents(self, documents: list, ids: list | None = None, metadatas: list | None = None):
        self._ensure_client()
        ids = ids or [f"doc_{i}" for i in range(len(documents))]
        metadatas = metadatas or [{}] * len(documents)
        self._collection.add(documents=documents, ids=ids, metadatas=metadatas)

    def search(self, query: str, k: int = 5, where: dict | None = None) -> list:
        self._ensure_client()
        n = min(k, self._collection.count())
        if n <= 0:
            return []
        res = self._collection.query(query_texts=[query], n_results=n, where=where)
        if not res or not res["ids"] or not res["ids"][0]:
            return []
        out = []
        for i, doc_id in enumerate(res["ids"][0]):
            doc = (res["documents"][0] or [])[i] if res.get("documents") else ""
            meta = (res["metadatas"][0] or [{}])[i] if res.get("metadatas") else {}
            dist = (res["distances"][0] or [0])[i] if res.get("distances") else 0
            out.append({"id": doc_id, "document": doc, "metadata": meta or {}, "distance": float(dist)})
        return out

    def count(self) -> int:
        self._ensure_client()
        return self._collection.count()


def get_retriever(collection_name: str, cfg: dict) -> RAGRetriever:
    return RAGRetriever(collection_name, cfg)
