"""Cheap file-type detection from magic bytes, with an extension fallback."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

MIME: dict[str, str] = {
    "zip": "application/zip",
    "rar": "application/vnd.rar",
    "7z": "application/x-7z-compressed",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "doc": "application/msword",
    "xls": "application/vnd.ms-excel",
    "ppt": "application/vnd.ms-powerpoint",
    "ole": "application/x-ole-storage",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "txt": "text/plain",
    "markdown": "text/markdown",
    "csv": "text/csv",
    "json": "application/json",
    "xml": "application/xml",
    "html": "text/html",
}

_EXT: dict[str, str] = {
    ".txt": "txt",
    ".text": "txt",
    ".log": "txt",
    ".md": "markdown",
    ".csv": "csv",
    ".json": "json",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".doc": "doc",
    ".xls": "xls",
    ".ppt": "ppt",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".gif": "gif",
    ".webp": "webp",
    ".zip": "zip",
    ".rar": "rar",
    ".7z": "7z",
}

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ARCHIVE_TYPES = {"zip", "rar", "7z"}


@dataclass(frozen=True)
class Detected:
    """``open_as`` is set only when magic bytes say this payload is an archive.

    Office packages are ZIP containers, but they are documents: ``open_as``
    stays ``None`` so the walker does not unpack ``word/document.xml``.
    An archive extension without a matching signature is not opened either.
    """

    file_type: str
    mime: str | None
    open_as: str | None = None


def signature_kind(header: bytes) -> str | None:
    """Classify a container from its leading bytes."""

    if header.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if header.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    return None


def _ooxml_kind(data: bytes) -> str | None:
    if not data.startswith(b"PK"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    return None


def ooxml_kind_from_zip(zf: zipfile.ZipFile) -> str | None:
    """Return docx/xlsx/pptx when ``zf`` is an Office package."""

    names = set(zf.namelist())
    if "[Content_Types].xml" not in names:
        return None
    if "word/document.xml" in names:
        return "docx"
    if "xl/workbook.xml" in names:
        return "xlsx"
    if "ppt/presentation.xml" in names:
        return "pptx"
    return None


def _magic(data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if data.startswith(_OLE):
        return "ole"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    return None


def detect(name: str, data: bytes) -> Detected:
    """Detect a member's type from its payload, then its suffix."""

    ext = _EXT.get(PurePosixPath(name).suffix.lower())
    magic = _magic(data)
    if magic == "zip":
        ooxml = _ooxml_kind(data)
        if ooxml:
            return Detected(ooxml, MIME.get(ooxml))
        return Detected("zip", MIME["zip"], "zip")
    if magic in {"rar", "7z"}:
        return Detected(magic, MIME.get(magic), magic)
    if magic == "ole":
        if ext in {"doc", "xls", "ppt"}:
            return Detected(ext, MIME.get(ext))
        return Detected("ole", MIME["ole"])
    if magic:
        return Detected(magic, MIME.get(magic))
    if ext and ext not in _ARCHIVE_TYPES:
        return Detected(ext, MIME.get(ext))
    if ext in _ARCHIVE_TYPES:
        # Extension claims an archive, but the bytes do not. Do not open it.
        return Detected(ext, MIME.get(ext))
    return Detected("unknown", None)
