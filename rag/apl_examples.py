"""
APL 示例 RAG 检索，供 generator 使用。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
_TOOLS_ROOT = Path(__file__).parent.parent
EXAMPLES_DIR = _TOOLS_ROOT / "generator" / "examples"
SHAREDEV_PULL_DIR = _TOOLS_ROOT / "sharedev_pull"
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
    sharedev_files = []
    if SHAREDEV_PULL_DIR.is_dir():
        sharedev_files = [p for p in SHAREDEV_PULL_DIR.rglob("*.apl") if p.is_file()]
    project_files = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            fpath = root_path / fname
            if _is_apl_file(fpath):
                project_files.append(fpath)
    builtin_names = {f.stem for f in builtin}
    sharedev_files = [f for f in sharedev_files if f.stem not in builtin_names]
    project_files = [f for f in project_files if f.stem not in builtin_names]
    known_res = {f.resolve() for f in builtin + sharedev_files}
    project_files = [f for f in project_files if f.resolve() not in known_res]
    return list(builtin) + sharedev_files + project_files


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


def retrieve_apl_examples(
    requirement: str,
    function_type: str,
    cfg: dict,
    num: int = 6,
    project_name: str | None = None,
    req_path: str | Path | None = None,
) -> list[dict]:
    """先按项目分层取示例，再用 RAG 补足槽位。返回项含 tier_label。"""
    from generator.prompt import load_examples

    tiered = load_examples(
        function_type,
        num,
        requirement,
        project_name=project_name,
        req_path=req_path,
    )
    seen_names = {e["filename"] for e in tiered}
    if len(tiered) >= num:
        return tiered[:num]

    from rag.retriever import RAGRetriever

    retriever = RAGRetriever("apl_examples", cfg)
    retriever._ensure_client()
    if retriever.count() == 0:
        build_apl_index(cfg)

    query = f"{function_type}\n{requirement}"
    hits = retriever.search(query, k=max(num * 3, 12))
    store = _load_content_store()
    merged = list(tiered)
    seen_dirs: dict = {}

    def _dir_key(path_str: str, filename: str) -> str:
        return Path(path_str).parent.name if path_str else filename

    for h in hits:
        if len(merged) >= num:
            break
        doc_id = h.get("id", "unknown")
        info = store.get(doc_id, {})
        content = info.get("content", h.get("document", ""))
        filename = info.get("filename", doc_id)
        if filename in seen_names:
            continue
        path_str = info.get("path", "") or ""
        dk = _dir_key(path_str, filename)
        if seen_dirs.get(dk, 0) >= 2:
            continue
        seen_dirs[dk] = seen_dirs.get(dk, 0) + 1
        norm = path_str.replace("\\", "/")
        label = "【语义检索】"
        pn = (project_name or "").strip()
        if pn and f"sharedev_pull/{pn}/" in norm:
            label = "【当前项目·语义检索】"
        merged.append({"filename": filename, "content": content, "tier_label": label})
        seen_names.add(filename)

    for e in merged:
        e.setdefault("tier_label", "【语义检索】")

    return merged[:num]
