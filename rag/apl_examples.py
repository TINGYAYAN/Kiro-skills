"""
APL 示例 RAG 检索，供 generator 使用。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
EXAMPLES_DIR = Path(__file__).parent.parent / "generator" / "examples"
CONTENT_STORE = Path(__file__).parent.parent / ".rag_index" / "apl_examples" / "content_store.json"

_SKIP_DIRS = {".git", ".cursor", ".trae", "_tools", "node_modules", "__pycache__", "插件"}
_APL_SIGNATURES = [
    "Fx.object.", "FQLAttribute", "QueryTemplate", "context.data",
    "UIEvent", "syncArg", "log.error", "log.info", "Fx.global.",
    "UpdateAttribute", "CreateAttribute", "SelectAttribute",
]


def _is_apl_file(path: Path) -> bool:
    if path.suffix.lower() != ".apl":
        return False
    try:
        head = path.read_bytes()[:2048].decode("utf-8", errors="ignore")
        return any(sig in head for sig in _APL_SIGNATURES)
    except Exception:
        return False


def _scan_apl_files() -> list[Path]:
    builtin = list(EXAMPLES_DIR.glob("*.apl")) if EXAMPLES_DIR.exists() else []
    project_files = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            fpath = root_path / fname
            if _is_apl_file(fpath):
                project_files.append(fpath)
    builtin_names = {f.stem for f in builtin}
    project_files = [f for f in project_files if f.stem not in builtin_names]
    return list(builtin) + project_files


def _load_content_store() -> dict:
    if CONTENT_STORE.exists():
        try:
            return json.loads(CONTENT_STORE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_content_store(store: dict):
    CONTENT_STORE.parent.mkdir(parents=True, exist_ok=True)
    CONTENT_STORE.write_text(json.dumps(store, ensure_ascii=False, indent=0), encoding="utf-8")


def build_apl_index(cfg: dict) -> int:
    """构建 APL 示例向量索引。返回索引的文档数量。"""
    from rag.retriever import RAGRetriever

    retriever = RAGRetriever("apl_examples", cfg)
    retriever._ensure_client()
    try:
        retriever._client.delete_collection("apl_examples")
    except Exception:
        pass
    retriever._collection = None
    retriever._ensure_client()

    files = _scan_apl_files()
    documents, ids, content_store = [], [], {}
    for fpath in files:
        try:
            content = fpath.read_text(encoding="utf-8")
            if len(content) < 100 or len(content) > 8000:
                continue
            search_text = f"{fpath.stem}\n{content[:2000]}"
            doc_id = fpath.stem
            if doc_id in ids:
                doc_id = f"{fpath.parent.name}_{fpath.stem}"
            documents.append(search_text)
            ids.append(doc_id)
            content_store[doc_id] = {"filename": fpath.stem, "content": content, "path": str(fpath)}
        except Exception:
            continue

    if documents:
        retriever.add_documents(documents, ids=ids)
        _save_content_store(content_store)
    return len(documents)


def retrieve_apl_examples(requirement: str, function_type: str, cfg: dict, num: int = 6) -> list[dict]:
    """基于 RAG 语义检索 APL 示例。返回 [{"filename", "content"}, ...]"""
    from rag.retriever import RAGRetriever

    retriever = RAGRetriever("apl_examples", cfg)
    retriever._ensure_client()
    if retriever.count() == 0:
        build_apl_index(cfg)

    query = f"{function_type}\n{requirement}"
    hits = retriever.search(query, k=num * 2)
    store = _load_content_store()
    seen_dirs, selected = {}, []
    for h in hits:
        doc_id = h.get("id", "unknown")
        info = store.get(doc_id, {})
        content = info.get("content", h.get("document", ""))
        filename = info.get("filename", doc_id)
        path_str = info.get("path", "")
        dir_key = Path(path_str).parent.name if path_str else filename
        if seen_dirs.get(dir_key, 0) >= 2:
            continue
        seen_dirs[dir_key] = seen_dirs.get(dir_key, 0) + 1
        selected.append({"filename": filename, "content": content})
        if len(selected) >= num:
            break
    if len(selected) < num:
        for h in hits:
            if len(selected) >= num:
                break
            doc_id = h.get("id", "unknown")
            info = store.get(doc_id, {})
            content = info.get("content", h.get("document", ""))
            filename = info.get("filename", doc_id)
            if not any(s["filename"] == filename for s in selected):
                selected.append({"filename": filename, "content": content})
    return selected[:num]
