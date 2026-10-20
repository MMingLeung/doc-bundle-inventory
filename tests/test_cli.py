"""CLI and module entry points."""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from doc_bundle_inventory.cli import main

from tests.ziputil import REPO_ROOT


def _zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("说明.txt", "你好\n".encode("utf-8"))


def test_cli_writes_utf8_manifest(tmp_path: Path) -> None:
    source = tmp_path / "bundle.zip"
    output = tmp_path / "out" / "manifest.json"
    _zip(source)

    code = main([str(source), "-o", str(output)])
    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "说明.txt" in text
    manifest = json.loads(text)
    assert manifest["schema_version"] == 1
    assert manifest["files"][0]["member_path"] == "说明.txt"


def test_cli_stdout_is_json(tmp_path: Path, capsys) -> None:
    source = tmp_path / "bundle.zip"
    _zip(source)
    code = main([str(source), "--indent", "0"])
    assert code == 0
    captured = capsys.readouterr()
    manifest = json.loads(captured.out)
    assert manifest["source"]["name"] == "bundle.zip"


def test_cli_missing_file(tmp_path: Path) -> None:
    code = main([str(tmp_path / "missing.zip")])
    assert code == 2


def test_module_entrypoint(tmp_path: Path) -> None:
    source = tmp_path / "bundle.zip"
    output = tmp_path / "manifest.json"
    _zip(source)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "doc_bundle_inventory",
            str(source),
            "-o",
            str(output),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["files"][0]["sha256"]
