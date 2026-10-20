"""The checked-in demo bundle and the generator that builds it."""

from __future__ import annotations

import hashlib
from pathlib import Path

from doc_bundle_inventory import inventory

from tests.ziputil import REPO_ROOT

SAMPLE = REPO_ROOT / "examples" / "sample_bundle" / "bundle.zip"


def test_checked_in_sample_manifest() -> None:
    assert SAMPLE.is_file()
    result = inventory(SAMPLE)
    _assert_demo_manifest(result)


def test_generator_matches_checked_in_sample(tmp_path: Path, sample_tools) -> None:
    generated = sample_tools.build_sample(tmp_path / "bundle.zip")
    fresh = inventory(generated)
    packed = inventory(SAMPLE)
    assert _stable_signature(fresh) == _stable_signature(packed)
    _assert_demo_manifest(fresh, tools=sample_tools)


def _assert_demo_manifest(result: dict, tools=None) -> None:
    by_member = {row["member_path"]: row for row in result["files"]}
    assert set(by_member) == {
        "说明.txt",
        "预览.png",
        "报告/项目说明_v1.0.txt",
        "报告/项目说明_v1.2_终稿.txt",
        "报告/副本/项目说明_v1.0.txt",
        "报告/说明_副本.txt",
        "报告/inner.zip",
        "附件/备注.txt",
        "附件/合同_终稿.docx",
        "附件/封面.pdf",
    }
    note = by_member["说明.txt"]
    assert note["name_encoding"] == "gb18030"
    assert note["logical_path"] == "bundle.zip!/说明.txt"
    expected_note = "这是一个嵌套压缩包示例。\n".encode("utf-8")
    assert note["sha256"] == hashlib.sha256(expected_note).hexdigest()
    assert by_member["报告/说明_副本.txt"]["duplicate_group"] == note["sha256"]
    assert by_member["报告/项目说明_v1.2_终稿.txt"]["version_hints"] == ["v1.2", "终稿"]
    assert by_member["报告/项目说明_v1.0.txt"]["version_hints"] == ["v1.0"]
    assert by_member["报告/inner.zip"]["kind"] == "archive"
    assert by_member["预览.png"]["file_type"] == "png"
    assert by_member["附件/备注.txt"]["logical_path"] == (
        "bundle.zip!/报告/inner.zip!/附件/备注.txt"
    )
    assert by_member["附件/备注.txt"]["archive_chain"] == ["bundle.zip", "报告/inner.zip"]

    docx = by_member["附件/合同_终稿.docx"]
    assert docx["file_type"] == "docx"
    assert docx["version_hints"] == ["终稿"]
    assert docx["metadata"]["author"] == "李明"
    assert docx["metadata"]["title"] == "示例合同"
    assert docx["metadata"]["page_count"] == 2

    pdf = by_member["附件/封面.pdf"]
    assert pdf["file_type"] == "pdf"
    assert pdf["metadata"]["author"] == "李明"
    assert pdf["metadata"]["title"] == "封面"
    assert pdf["metadata"]["page_count"] == 1
    assert pdf["metadata"]["modified"] == "2024-06-01T09:00:00Z"

    assert result["stats"]["files"] == 9
    assert result["stats"]["nested_archives"] == 1
    assert result["stats"]["directories"] == 3
    assert result["stats"]["duplicate_groups"] == 2
    assert result["warnings"] == []
    assert {group["count"] for group in result["duplicates"]} == {2}
    if tools is not None:
        assert by_member["预览.png"]["sha256"] == hashlib.sha256(tools.build_png()).hexdigest()


def _stable_signature(result: dict) -> list[tuple]:
    rows = []
    for row in result["files"]:
        digest = row["sha256"] if row["file_type"] == "txt" else None
        meta = None
        if row["metadata"]:
            meta = (
                row["metadata"]["title"],
                row["metadata"]["author"],
                row["metadata"]["modified"],
                row["metadata"]["page_count"],
            )
        rows.append(
            (
                row["logical_path"],
                row["file_type"],
                row["name_encoding"],
                tuple(row["version_hints"]),
                digest,
                meta,
                row["duplicate_group"] is not None,
            )
        )
    return rows
