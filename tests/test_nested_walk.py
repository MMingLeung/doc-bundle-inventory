"""Nested ZIP walking."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

from doc_bundle_inventory import inventory

from tests.ziputil import STAMP


def test_nested_zip_lists_inner_file_and_hash(tmp_path: Path) -> None:
    payload = b"hello inner"
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("notes/readme.txt", payload)
    outer = tmp_path / "bundle.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("top.txt", b"hello top")
        archive.writestr("nested/inner.zip", inner.getvalue())

    result = inventory(outer)
    by_path = {row["member_path"]: row for row in result["files"]}

    assert "top.txt" in by_path
    assert "nested/inner.zip" in by_path
    assert by_path["nested/inner.zip"]["kind"] == "archive"
    assert "notes/readme.txt" in by_path
    inner_row = by_path["notes/readme.txt"]
    assert inner_row["logical_path"] == "bundle.zip!/nested/inner.zip!/notes/readme.txt"
    assert inner_row["archive_chain"] == ["bundle.zip", "nested/inner.zip"]
    assert inner_row["sha256"] == hashlib.sha256(payload).hexdigest()
    assert inner_row["file_type"] == "txt"

    logicals = _logical_paths(result["tree"])
    assert "bundle.zip!/nested/inner.zip!/notes/readme.txt" in logicals


def test_docx_is_not_unpacked(tmp_path: Path, sample_tools) -> None:
    outer = tmp_path / "bundle.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        info = zipfile.ZipInfo("合同.docx", date_time=STAMP)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, sample_tools.build_docx())

    result = inventory(outer)
    paths = [row["member_path"] for row in result["files"]]
    assert paths == ["合同.docx"]
    assert result["files"][0]["file_type"] == "docx"
    assert result["files"][0]["metadata"]["author"] == sample_tools.AUTHOR
    assert result["files"][0]["metadata"]["page_count"] == 2
    assert all("word/document.xml" not in path for path in paths)


def _logical_paths(node: dict) -> set[str]:
    found = {node["logical_path"]}
    for child in node.get("children") or []:
        found |= _logical_paths(child)
    return found
