"""Duplicate hints from identical uncompressed bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path

from doc_bundle_inventory import inventory


def test_same_hash_is_grouped(tmp_path: Path) -> None:
    payload = b"same-bytes"
    path = tmp_path / "dup.zip"
    import zipfile

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a/one.txt", payload)
        archive.writestr("b/two.txt", payload)
        archive.writestr("c/three.txt", b"different")

    result = inventory(path)
    assert len(result["duplicates"]) == 1
    group = result["duplicates"][0]
    assert group["count"] == 2
    assert group["sha256"] == hashlib.sha256(payload).hexdigest()
    assert group["paths"] == [
        "dup.zip!/a/one.txt",
        "dup.zip!/b/two.txt",
    ]
    grouped = {
        row["logical_path"]: row["duplicate_group"]
        for row in result["files"]
    }
    assert grouped["dup.zip!/a/one.txt"] == group["sha256"]
    assert grouped["dup.zip!/b/two.txt"] == group["sha256"]
    assert grouped["dup.zip!/c/three.txt"] is None


def test_empty_files_are_not_duplicate_hints(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "empty.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.txt", b"")
        archive.writestr("b.txt", b"")

    result = inventory(path)
    assert result["duplicates"] == []
    assert all(row["duplicate_group"] is None for row in result["files"])
