from __future__ import annotations

import json
import os
import re
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent
SHAREDEV_PULL_DIR = TOOLS_DIR / "sharedev_pull"
PROJECT_ROOT = TOOLS_DIR.parent
CACHE_DIR = TOOLS_DIR / ".rag_index" / "reference_examples"
CACHE_FILE = CACHE_DIR / "entries.json"
CACHE_VERSION = 1

_SKIP_DIRS = {".git", ".cursor", ".trae", "_tools", "node_modules", "__pycache__", "插件", ".rag_index"}
_SKIP_EXTS = {
    ".js", ".vue", ".md", ".json", ".yml", ".yaml", ".txt", ".png", ".jpg", ".zip",
    ".jar", ".DS_Store", ".py", ".html", ".css", ".ts", ".java", ".xml",
}
_APL_SIGNATURES = [
    "Fx.object.", "FQLAttribute", "QueryTemplate", "context.data",
    "UIEvent", "syncArg", "log.error", "log.info", "Fx.global.",
    "UpdateAttribute", "CreateAttribute", "SelectAttribute",
]

_MEMO_MANIFEST: list[dict] | None = None
_MEMO_ENTRIES: list[dict] | None = None


def _is_apl_file(path: Path) -> bool:
    if path.suffix.lower() in _SKIP_EXTS:
        return False
    if path.suffix.lower() == ".apl":
        return True
    if path.suffix == "":
        try:
            head = path.read_bytes()[:2048].decode("utf-8", errors="ignore")
            return any(sig in head for sig in _APL_SIGNATURES)
        except Exception:
            return False
    return False


def _parse_code_name_from_body(content: str) -> str:
    if not content:
        return ""
    m = re.search(r"@codeName\s+([^\n\r*]+)", content)
    return m.group(1).strip() if m else ""


def _workspace_apl_sources() -> list[dict]:
    out: list[dict] = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for fname in files:
            fpath = root_path / fname
            if not _is_apl_file(fpath):
                continue
            out.append({
                "path": str(fpath.resolve()),
                "kind": "workspace_apl",
                "project_name": "",
            })
    return out


def _sharedev_apl_sources() -> list[dict]:
    out: list[dict] = []
    if not SHAREDEV_PULL_DIR.is_dir():
        return out
    for proj_dir in sorted(SHAREDEV_PULL_DIR.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        for fpath in proj_dir.rglob("*.apl"):
            if fpath.is_file():
                out.append({
                    "path": str(fpath.resolve()),
                    "kind": "sharedev_apl",
                    "project_name": proj_dir.name,
                })
    return out


def _functions_json_sources() -> list[dict]:
    out: list[dict] = []
    if not SHAREDEV_PULL_DIR.is_dir():
        return out
    for proj_dir in sorted(SHAREDEV_PULL_DIR.iterdir()):
        if not proj_dir.is_dir() or proj_dir.name.startswith("."):
            continue
        fpath = proj_dir / "functions.json"
        if fpath.exists():
            out.append({
                "path": str(fpath.resolve()),
                "kind": "functions_json",
                "project_name": proj_dir.name,
            })
    return out


def _build_manifest() -> list[dict]:
    manifest: list[dict] = []
    for src in _functions_json_sources() + _sharedev_apl_sources() + _workspace_apl_sources():
        try:
            st = Path(src["path"]).stat()
        except FileNotFoundError:
            continue
        manifest.append({
            "path": src["path"],
            "kind": src["kind"],
            "project_name": src["project_name"],
            "mtime_ns": int(st.st_mtime_ns),
            "size": int(st.st_size),
        })
    manifest.sort(key=lambda x: (x["kind"], x["project_name"], x["path"]))
    return manifest


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(manifest: list[dict], entries: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(
            {
                "version": CACHE_VERSION,
                "manifest": manifest,
                "entries": entries,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _entries_from_functions_json(path: Path, project_name: str) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data if isinstance(data, list) else (data.get("items") or data.get("data") or [])
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = (item.get("body") or "").strip()
        if len(content) < 100 or len(content) > 12000:
            continue
        if item.get("is_current") is False:
            continue
        lang = str(item.get("lang") or "").lower()
        if lang and lang not in ("groovy", "apl"):
            continue
        filename = (
            _parse_code_name_from_body(content)
            or str(item.get("function_name") or "").strip()
            or str(item.get("api_name") or "").strip()
            or "unknown_function"
        )
        source_key = str(item.get("api_name") or filename)
        out.append({
            "source_key": source_key,
            "filename": filename,
            "content": content,
            "project_name": project_name,
            "source_kind": "functions_json",
            "path": str(path),
            "search_text": "\n".join([
                project_name,
                filename,
                str(item.get("binding_object_label") or ""),
                str(item.get("binding_object_api_name") or ""),
                str(item.get("name_space") or ""),
                content[:2500],
            ]).strip(),
        })
    return out


def _entries_from_apl(path: Path, source_kind: str, project_name: str) -> list[dict]:
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return []
    if len(content) < 100 or len(content) > 12000:
        return []
    filename = _parse_code_name_from_body(content) or path.stem
    return [{
        "source_key": f"{source_kind}:{path}",
        "filename": filename,
        "content": content,
        "project_name": project_name,
        "source_kind": source_kind,
        "path": str(path),
        "search_text": "\n".join([
            project_name,
            filename,
            content[:2500],
        ]).strip(),
    }]


def _rebuild_entries(manifest: list[dict]) -> list[dict]:
    entries: list[dict] = []
    for src in manifest:
        path = Path(src["path"])
        kind = src["kind"]
        proj = src["project_name"]
        if kind == "functions_json":
            entries.extend(_entries_from_functions_json(path, proj))
        else:
            entries.extend(_entries_from_apl(path, kind, proj))
    return entries


def load_reference_entries(force_refresh: bool = False) -> list[dict]:
    global _MEMO_ENTRIES, _MEMO_MANIFEST
    manifest = _build_manifest()
    if not force_refresh and _MEMO_MANIFEST == manifest and _MEMO_ENTRIES is not None:
        return list(_MEMO_ENTRIES)

    cache = {} if force_refresh else _load_cache()
    if (
        not force_refresh
        and cache.get("version") == CACHE_VERSION
        and cache.get("manifest") == manifest
        and isinstance(cache.get("entries"), list)
    ):
        entries = cache["entries"]
    else:
        entries = _rebuild_entries(manifest)
        _save_cache(manifest, entries)

    _MEMO_MANIFEST = manifest
    _MEMO_ENTRIES = list(entries)
    return list(entries)
