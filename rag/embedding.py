"""Embedding 封装，支持 OpenAI 及兼容 API。"""
from __future__ import annotations

import os
from typing import Optional


def get_embedding_client(cfg: dict):
    """根据配置返回 ChromaDB 可用的 embedding function。"""
    try:
        import chromadb.utils.embedding_functions as ef
    except ImportError:
        raise ImportError("请安装 chromadb: pip install chromadb")

    llm = cfg.get("llm") or {}
    rag_cfg = cfg.get("rag") or {}
    api_key = (
        rag_cfg.get("api_key")
        or llm.get("api_key")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
    )
    model = rag_cfg.get("embedding_model") or "text-embedding-3-small"
    base_url = rag_cfg.get("base_url") or llm.get("base_url")

    openai_kw = {
        "model_name": model,
        "api_key": api_key,
    }
    if base_url:
        openai_kw["api_base"] = base_url.rstrip("/").replace("/v1", "") + "/v1"

    return ef.OpenAIEmbeddingFunction(**{k: v for k, v in openai_kw.items() if v})


def embed_texts(texts: list[str], cfg: dict) -> list[list[float]]:
    """批量获取文本的 embedding 向量。"""
    ef = get_embedding_client(cfg)
    return ef(texts)
