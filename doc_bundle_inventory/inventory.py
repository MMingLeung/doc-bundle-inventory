"""Build a manifest for a nested document archive."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from doc_bundle_inventory.archive import Member, WalkState, collect
from doc_bundle_inventory.errors import InventoryError
from doc_bundle_inventory.limits import (
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_UNCOMPRESSED_BYTES,
    DEFAULT_RATIO_MIN_BYTES,
    Limits,
)
from doc_bundle_inventory.sniff import signature_kind

SCHEMA_VERSION = 1


def inventory(
    path: str | Path,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_files: int = DEFAULT_MAX_FILES,
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO,
    ratio_min_bytes: int = DEFAULT_RATIO_MIN_BYTES,
) -> dict[str, Any]:
    """Inventory ``path`` and return a JSON-ready manifest dict.

    The walk lists every nested ZIP member it is allowed to read, hashes the
    uncompressed bytes, and adds duplicate groups for identical non-empty
    payloads. Word and PDF metadata is included when it can be read cheaply.
    """

    limits = Limits(
        max_depth=max_depth,
        max_uncompressed_bytes=max_uncompressed_bytes,
        max_file_bytes=max_file_bytes,
        max_files=max_files,
        max_compression_ratio=max_compression_ratio,
        ratio_min_bytes=ratio_min_bytes,
    )
    try:
        limits.validate()
    except ValueError as exc:
        raise InventoryError(str(exc)) from exc

    source = Path(path).expanduser()
    if not source.is_file():
        raise InventoryError(f"not a file: {source}")

    state = collect(source, limits)
    _assign_duplicates(state)
    file_rows = [_member_dict(member) for member in state.members if member.kind != "directory"]
    source_hash = _sha256_file(source)
    source_size = source.stat().st_size
    with source.open("rb") as handle:
        source_format = signature_kind(handle.read(8)) or "unknown"
    tree = _build_tree(source.name, source_format, source_size, source_hash, state.members)
    duplicate_rows = _duplicate_rows(state)

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "path": str(path),
            "name": source.name,
            "format": source_format,
            "size": source_size,
            "sha256": source_hash,
        },
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limits": limits.to_dict(),
        "stats": {
            "files": sum(1 for member in state.members if member.kind == "file"),
            "nested_archives": sum(1 for member in state.members if member.kind == "archive"),
            "directories": _count_kind(tree, "directory"),
            "duplicate_groups": len(duplicate_rows),
            "warnings": len(state.warnings),
            "uncompressed_bytes": state.uncompressed,
            "members_considered": state.seen,
        },
        "warnings": state.warnings,
        "duplicates": duplicate_rows,
        "files": file_rows,
        "tree": tree,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assign_duplicates(state: WalkState) -> None:
    grouped: dict[str, list[Member]] = {}
    for member in state.members:
        if member.kind == "directory" or not member.sha256 or not member.size:
            continue
        grouped.setdefault(member.sha256, []).append(member)
    duplicated = {digest for digest, members in grouped.items() if len(members) >= 2}
    for member in state.members:
        if member.sha256 in duplicated:
            member.duplicate_group = member.sha256


def _duplicate_rows(state: WalkState) -> list[dict[str, Any]]:
    grouped: dict[str, list[Member]] = {}
    for member in state.members:
        if member.duplicate_group and member.sha256:
            grouped.setdefault(member.sha256, []).append(member)
    rows = []
    for digest, members in grouped.items():
        rows.append(
            {
                "sha256": digest,
                "size": members[0].size,
                "count": len(members),
                "paths": [member.logical_path for member in members],
            }
        )
    return rows


def _member_dict(member: Member) -> dict[str, Any]:
    return {
        "logical_path": member.logical_path,
        "member_path": member.member_path,
        "archive_chain": list(member.containers),
        "kind": member.kind,
        "file_type": member.file_type,
        "mime": member.mime,
        "size": member.size,
        "sha256": member.sha256,
        "name_encoding": member.name_encoding,
        "version_hints": member.version_hints,
        "metadata": member.metadata,
        "duplicate_group": member.duplicate_group,
    }


def _build_tree(
    source_name: str,
    source_format: str,
    source_size: int,
    source_sha256: str,
    members: list[Member],
) -> dict[str, Any]:
    root: dict[str, Any] = {
        "name": source_name,
        "path": source_name,
        "logical_path": source_name,
        "kind": "archive",
        "file_type": source_format,
        "size": source_size,
        "sha256": source_sha256,
        "children": [],
    }
    archives = {source_name: root}
    for member in members:
        parent_key = "!/".join(member.containers)
        parent = archives.get(parent_key)
        if parent is None:
            continue
        parts = [part for part in member.member_path.split("/") if part]
        if not parts:
            continue
        if member.kind == "directory":
            _ensure_dirs(parent, parent_key, parts)
            continue
        folder = _ensure_dirs(parent, parent_key, parts[:-1])
        node: dict[str, Any] = {
            "name": parts[-1],
            "path": member.member_path,
            "logical_path": member.logical_path,
            "kind": member.kind,
            "file_type": member.file_type,
            "size": member.size,
            "sha256": member.sha256,
        }
        if member.kind == "archive":
            node["children"] = []
            archives[member.logical_path] = node
        folder["children"].append(node)
    return root


def _ensure_dirs(parent: dict[str, Any], parent_logical: str, parts: list[str]) -> dict[str, Any]:
    cursor = parent
    acc: list[str] = []
    for part in parts:
        acc.append(part)
        found = None
        for child in cursor["children"]:
            if child["name"] == part and child["kind"] == "directory":
                found = child
                break
        if found is None:
            rel = "/".join(acc)
            found = {
                "name": part,
                "path": rel,
                "logical_path": f"{parent_logical}!/{rel}",
                "kind": "directory",
                "file_type": "directory",
                "size": None,
                "sha256": None,
                "children": [],
            }
            cursor["children"].append(found)
        cursor = found
    return cursor


def _count_kind(node: dict[str, Any], kind: str) -> int:
    total = 1 if node.get("kind") == kind else 0
    for child in node.get("children") or []:
        total += _count_kind(child, kind)
    return total
