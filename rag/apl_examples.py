"""
APL 示例 RAG 检索，供 generator 使用。
"""
from __future__ import annotations

import json
from pathlib import Path

from generator.example_index import load_reference_entries

CONTENT_STORE = Path(__file__).parent.parent / ".rag_index" / "apl_examples" / "content_store.json"


def _load_content_store() -> dict:
    if CONTENT_STORE.exists():
        try:
            return json.loads(CONTENT_STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_content_store(store: dict):
    CONTENT_STORE.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_STORE.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build_apl_index(cfg: dict) -> int:
    """基于本地参考函数索引构建 APL 向量索引。"""
    from rag.retriever import RAGRetriever

    retriever = RAGRetriever("apl_examples", cfg)
    retriever._ensure_client()
    try:
        retriever._client.delete_collection("apl_examples")
    except Exception:
        pass
    retriever._collection = None
    retriever._ensure_client()

    entries = load_reference_entries(force_refresh=False)
    documents, ids, metadatas, content_store = [], [], [], {}
    seen_ids: set[str] = set()
    for entry in entries:
        content = (entry.get("content") or "").strip()
        if len(content) < 100 or len(content) > 12000:
            continue
        doc_id = str(entry.get("source_key") or entry.get("filename") or "unknown")
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        documents.append(entry.get("search_text") or f"{entry.get('filename')}\n{content[:2500]}")
        ids.append(doc_id)
        metadatas.append({
            "project_name": entry.get("project_name") or "",
            "source_kind": entry.get("source_kind") or "",
            "filename": entry.get("filename") or doc_id,
        })
        content_store[doc_id] = {
            "filename": entry.get("filename") or doc_id,
            "content": content,
            "path": entry.get("path") or "",
            "project_name": entry.get("project_name") or "",
            "source_kind": entry.get("source_kind") or "",
        }

    if documents:
        retriever.add_documents(documents, ids=ids, metadatas=metadatas)
        _save_content_store(content_store)
    return len(documents)


def retrieve_apl_examples(
    requirement: str,
    function_type: str,
    cfg: dict,
    num: int = 6,
    project_name: str | None = None,
    req_path: str | Path | None = None,
) -> list[dict]:
    """先按结构化索引分层取示例，再用 RAG 补足槽位。"""
    from generator.prompt import load_examples

    tiered = load_examples(
        function_type,
        num,
        requirement,
        project_name=project_name,
        req_path=req_path,
    )
    seen_keys = {f"{e.get('tier_label')}::{e['filename']}" for e in tiered}
    if len(tiered) >= num:
        return tiered[:num]

    from rag.retriever import RAGRetriever

    retriever = RAGRetriever("apl_examples", cfg)
    retriever._ensure_client()
    if retriever.count() == 0:
        build_apl_index(cfg)

    query = f"{function_type}\n{requirement}"
    hits = retriever.search(query, k=max(num * 4, 16))
    store = _load_content_store()
    merged = list(tiered)
    seen_projects: dict = {}
    target_project = (project_name or "").strip()

    for h in hits:
        if len(merged) >= num:
            break
        doc_id = h.get("id", "unknown")
        info = store.get(doc_id, {})
        content = info.get("content", h.get("document", ""))
        filename = info.get("filename", doc_id)
        proj = (info.get("project_name") or "").strip()
        source_kind = info.get("source_kind") or ""
        label = "【其他项目·语义检索】"
        if target_project and proj == target_project:
            label = "【当前项目·语义检索】"
        elif source_kind == "workspace_apl":
            label = "【历史代码·语义检索】"
        dedupe_key = f"{label}::{filename}"
        if dedupe_key in seen_keys:
            continue
        if seen_projects.get(proj or source_kind, 0) >= 2:
            continue
        seen_projects[proj or source_kind] = seen_projects.get(proj or source_kind, 0) + 1
        merged.append({
            "filename": filename,
            "content": content,
            "tier_label": label,
        })
        seen_keys.add(dedupe_key)

    for e in merged:
        e.setdefault("tier_label", "【语义检索】")

    return merged[:num]
