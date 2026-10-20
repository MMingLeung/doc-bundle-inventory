"""Small ZIP writers shared by tests. Not part of the library."""

from __future__ import annotations

import zipfile
from pathlib import Path

STAMP = (2024, 6, 1, 9, 0, 0)
REPO_ROOT = Path(__file__).resolve().parents[1]


class EncodedZipInfo(zipfile.ZipInfo):
    """Write a member name in a chosen encoding with the UTF-8 flag clear."""

    def __init__(self, filename: str, encoding: str):
        super().__init__(filename=filename, date_time=STAMP)
        self._raw_encoding = encoding

    def _encodeFilenameFlags(self):  # noqa: N802 — zipfile hook
        return self.filename.encode(self._raw_encoding), self.flag_bits & ~0x800


def write_zip(path: Path, items: list[tuple[str, bytes, str | None]]) -> None:
    """Write ``items`` as ``(name, data, encoding)``.

    ``encoding`` None uses zipfile's default (UTF-8 when the name is not ASCII).
    """

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data, encoding in items:
            if encoding:
                info: zipfile.ZipInfo = EncodedZipInfo(name, encoding)
            else:
                info = zipfile.ZipInfo(filename=name, date_time=STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
