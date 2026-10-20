"""Path traversal, size, depth, and ratio guards."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from doc_bundle_inventory import inventory
from doc_bundle_inventory.names import analyze_member_path

from tests.ziputil import STAMP


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("../x", "path_traversal"),
        ("a/../../b", "path_traversal"),
        ("..\\..\\secret.txt", "path_traversal"),
        ("/etc/passwd", "absolute_path"),
        ("C:/Windows/x.txt", "absolute_path"),
        ("\\\\server\\share\\x", "absolute_path"),
        ("a\\b\\c.txt", None),
        ("报告/a.txt", None),
        ("a/\x00b", "null_byte"),
    ],
)
def test_analyze_member_path(name: str, code: str | None) -> None:
    _normalized, error = analyze_member_path(name)
    assert error == code


def test_path_traversal_is_rejected_and_content_is_dropped(tmp_path: Path) -> None:
    secret = b"pwned-secret-value"
    path = tmp_path / "slip.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../../etc/passwd", secret)
        archive.writestr("/tmp/evil.txt", b"absolute")
        archive.writestr("ok/../../escape.txt", b"also-secret")
        archive.writestr("ok/file.txt", b"kept")

    result = inventory(path)
    rendered = json.dumps(result, ensure_ascii=False)
    assert [row["member_path"] for row in result["files"]] == ["ok/file.txt"]
    assert "pwned-secret-value" not in rendered
    assert "also-secret" not in rendered
    codes = {warning["code"] for warning in result["warnings"]}
    assert "path_traversal" in codes
    assert "absolute_path" in codes


def test_backslash_traversal_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "slash.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("..\\..\\secret.txt", b"nope")
        archive.writestr("kept.txt", b"yes")

    result = inventory(path)
    assert [row["member_path"] for row in result["files"]] == ["kept.txt"]
    assert any(warning["code"] == "path_traversal" for warning in result["warnings"])


def test_oversize_member_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "big.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("big.bin", b"A" * 200)
        archive.writestr("small.txt", b"ok")

    result = inventory(path, max_file_bytes=100)
    assert [row["member_path"] for row in result["files"]] == ["small.txt"]
    assert any(warning["code"] == "max_file_bytes" for warning in result["warnings"])


def test_uncompressed_budget(tmp_path: Path) -> None:
    path = tmp_path / "budget.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a.txt", b"a" * 30)
        archive.writestr("b.txt", b"b" * 30)

    result = inventory(path, max_uncompressed_bytes=40)
    assert [row["member_path"] for row in result["files"]] == ["a.txt"]
    assert any(warning["code"] == "max_uncompressed_bytes" for warning in result["warnings"])


def test_compression_ratio_guard(tmp_path: Path) -> None:
    path = tmp_path / "bomb.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.bin", b"\0" * 65536)
        archive.writestr("ok.txt", b"hello")

    result = inventory(path, max_compression_ratio=30, ratio_min_bytes=1024)
    assert [row["member_path"] for row in result["files"]] == ["ok.txt"]
    assert any(warning["code"] == "compression_ratio" for warning in result["warnings"])


def test_max_depth_stops_nested_open(tmp_path: Path) -> None:
    import io

    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("leaf.txt", b"leaf")
    mid = io.BytesIO()
    with zipfile.ZipFile(mid, "w") as archive:
        archive.writestr("inner.zip", inner.getvalue())
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("mid.zip", mid.getvalue())

    stopped = inventory(outer, max_depth=2)
    stopped_paths = {row["member_path"] for row in stopped["files"]}
    assert "mid.zip" in stopped_paths
    assert "inner.zip" in stopped_paths
    assert "leaf.txt" not in stopped_paths
    assert any(warning["code"] == "max_depth" for warning in stopped["warnings"])

    opened = inventory(outer, max_depth=3)
    assert any(row["member_path"] == "leaf.txt" for row in opened["files"])


def test_max_files(tmp_path: Path) -> None:
    path = tmp_path / "many.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(4):
            archive.writestr(f"{index}.txt", b"x")

    result = inventory(path, max_files=2)
    assert [row["member_path"] for row in result["files"]] == ["0.txt", "1.txt"]
    assert any(warning["code"] == "max_files" for warning in result["warnings"])


def test_symlink_member_is_skipped(tmp_path: Path) -> None:
    path = tmp_path / "link.zip"
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("escape", date_time=STAMP)
        info.external_attr = 0o120777 << 16
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, b"/tmp/secret")
        archive.writestr("ok.txt", b"ok")

    result = inventory(path)
    assert [row["member_path"] for row in result["files"]] == ["ok.txt"]
    assert any(warning["code"] == "symlink" for warning in result["warnings"])
