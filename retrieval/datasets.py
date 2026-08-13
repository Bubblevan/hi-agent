"""Helpers for reproducible local RAG test datasets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def load_rag_manifest(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate a checked-in RAG fixture manifest."""
    manifest_path = Path(path).resolve()
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    if not isinstance(manifest, dict):
        raise ValueError("RAG manifest top level must be an object")
    if manifest.get("version") != 1:
        raise ValueError("unsupported RAG manifest version")
    if not isinstance(manifest.get("dataset_id"), str):
        raise ValueError("RAG manifest requires dataset_id")

    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("RAG manifest requires a non-empty sources list")

    required = {"id", "kind", "path", "user_id", "namespace", "bytes", "sha256"}
    for source in sources:
        if not isinstance(source, dict) or not required <= source.keys():
            raise ValueError("each RAG source must contain the required fields")
        if source["kind"] not in {"pdf", "markdown"}:
            raise ValueError(f"unsupported RAG fixture kind: {source['kind']}")
        if not isinstance(source["bytes"], int) or source["bytes"] < 1:
            raise ValueError(f"invalid byte count for RAG source: {source['id']}")
        digest = source["sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or digest != digest.lower():
            raise ValueError(f"invalid sha256 for RAG source: {source['id']}")

    return manifest


def resolve_source_path(
    source: dict[str, Any], *, project_root: str | Path
) -> Path:
    """Resolve a manifest path relative to the Hi-Agent project root."""
    relative_path = Path(source["path"])
    if relative_path.is_absolute():
        raise ValueError(f"RAG manifest paths must be relative: {source['id']}")
    return (Path(project_root).resolve() / relative_path).resolve()


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 digest of a fixture without loading it all at once."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
