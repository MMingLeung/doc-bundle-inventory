"""GBK filenames written without the ZIP UTF-8 flag."""

from __future__ import annotations

from pathlib import Path

from doc_bundle_inventory import inventory
from doc_bundle_inventory.names import recover_zip_filename

from tests.ziputil import write_zip


def test_recover_gbk_from_cp437_roundtrip() -> None:
    original = "说明.txt"
    mojibake = original.encode("gbk").decode("cp437")
    name, encoding = recover_zip_filename(mojibake, 0)
    assert name == original
    assert encoding == "gb18030"


def test_utf8_flag_is_left_alone() -> None:
    name, encoding = recover_zip_filename("报告.txt", 0x800)
    assert name == "报告.txt"
    assert encoding == "utf-8"


def test_zip_gbk_name_is_recovered(tmp_path: Path) -> None:
    path = tmp_path / "names.zip"
    payload = "你好".encode("utf-8")
    write_zip(
        path,
        [
            ("说明.txt", payload, "gbk"),
            ("报告/备注.txt", "utf-8 name".encode("utf-8"), None),
        ],
    )

    result = inventory(path)
    by_path = {row["member_path"]: row for row in result["files"]}
    assert "说明.txt" in by_path
    assert by_path["说明.txt"]["name_encoding"] == "gb18030"
    assert by_path["说明.txt"]["logical_path"] == "names.zip!/说明.txt"
    assert by_path["报告/备注.txt"]["name_encoding"] == "utf-8"
    assert not any(row["member_path"].startswith("╨") for row in result["files"])
