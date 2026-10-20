"""Lightweight Word and PDF metadata.

Only fields that are cheap to read are returned: title, author, modified
time, and page count. There is no text extraction and no OCR.
"""

from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

_PDF_KEYS = ("Title", "Author", "ModDate")
_PDF_STRING = {
    key: re.compile(
        r"/" + key + r"\s*(\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]+>)"
    )
    for key in _PDF_KEYS
}
_PDF_DATE = re.compile(
    r"^D:(?P<y>\d{4})(?P<mo>\d{2})?(?P<d>\d{2})?"
    r"(?P<h>\d{2})?(?P<mi>\d{2})?(?P<s>\d{2})?"
    r"(?P<tz>Z|[+-]\d{2}'?\d{2}'?)?$"
)
_PAGES_COUNT = re.compile(r"/Type\s*/Pages\b.{0,300}?/Count\s+(\d+)", re.DOTALL)
_PAGE_OBJECTS = re.compile(r"/Type\s*/Page\b(?!s)")


def extract_metadata(file_type: str, data: bytes) -> dict | None:
    """Return a metadata dict for docx/pdf, otherwise ``None``."""

    if file_type == "docx":
        return _docx_metadata(data)
    if file_type == "pdf":
        return _pdf_metadata(data)
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx_metadata(data: bytes) -> dict:
    meta: dict[str, str | int | None] = {
        "title": None,
        "author": None,
        "modified": None,
        "page_count": None,
    }
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            core = zf.read("docProps/core.xml") if "docProps/core.xml" in names else b""
            app = zf.read("docProps/app.xml") if "docProps/app.xml" in names else b""
    except zipfile.BadZipFile:
        return meta
    if core:
        _fill_core(meta, core)
    if app:
        _fill_pages(meta, app)
    return meta


def _fill_core(meta: dict, xml_bytes: bytes) -> None:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return
    for element in root.iter():
        name = _local(element.tag)
        text = (element.text or "").strip()
        if not text:
            continue
        if name in {"title", "creator", "modified"}:
            key = "author" if name == "creator" else name
            meta[key] = text


def _fill_pages(meta: dict, xml_bytes: bytes) -> None:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return
    for element in root.iter():
        if _local(element.tag) != "Pages":
            continue
        text = (element.text or "").strip()
        if text.isdigit():
            meta["page_count"] = int(text)
            return


def _pdf_metadata(data: bytes) -> dict:
    meta: dict[str, str | int | None] = {
        "title": None,
        "author": None,
        "modified": None,
        "page_count": None,
    }
    if len(data) <= 2_000_000:
        window = data
    else:
        window = data[:1_000_000] + b"\n" + data[-1_000_000:]
    text = window.decode("latin-1", errors="ignore")
    values = {key: _last_pdf_string(text, key) for key in _PDF_KEYS}
    meta["title"] = values["Title"]
    meta["author"] = values["Author"]
    if values["ModDate"]:
        meta["modified"] = _normalize_pdf_date(values["ModDate"])
    meta["page_count"] = _pdf_page_count(text)
    return meta


def _last_pdf_string(text: str, key: str) -> str | None:
    matches = list(_PDF_STRING[key].finditer(text))
    if not matches:
        return None
    return _decode_pdf_string(matches[-1].group(1))


def _decode_pdf_string(token: str) -> str | None:
    if token.startswith("("):
        decoded = _unescape_pdf_literal(token[1:-1])
    else:
        hex_body = re.sub(r"\s+", "", token[1:-1])
        if len(hex_body) % 2:
            hex_body += "0"
        try:
            raw = bytes.fromhex(hex_body)
        except ValueError:
            return None
        if raw.startswith(b"\xfe\xff"):
            decoded = raw[2:].decode("utf-16-be", errors="ignore")
        elif raw.startswith(b"\xff\xfe"):
            decoded = raw[2:].decode("utf-16-le", errors="ignore")
        else:
            decoded = raw.decode("latin-1", errors="ignore")
            decoded = _maybe_utf8(decoded)
    cleaned = decoded.replace("\x00", "").strip()
    return cleaned or None


def _unescape_pdf_literal(body: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\" or index + 1 >= len(body):
            out.append(char)
            index += 1
            continue
        nxt = body[index + 1]
        mapping = {
            "n": "\n",
            "r": "\r",
            "t": "\t",
            "b": "\b",
            "f": "\f",
            "(": "(",
            ")": ")",
            "\\": "\\",
        }
        if nxt in mapping:
            out.append(mapping[nxt])
            index += 2
            continue
        if nxt.isdigit():
            octal = nxt
            cursor = index + 2
            while cursor < len(body) and len(octal) < 3 and body[cursor].isdigit():
                octal += body[cursor]
                cursor += 1
            out.append(chr(int(octal, 8) & 0xFF))
            index = cursor
            continue
        out.append(nxt)
        index += 2
    return _maybe_utf8("".join(out))


def _maybe_utf8(text: str) -> str:
    raw = text.encode("latin-1", errors="ignore")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return text


def _normalize_pdf_date(value: str) -> str:
    match = _PDF_DATE.match(value.strip())
    if not match:
        return value.strip()
    year = match.group("y")
    month = match.group("mo") or "01"
    day = match.group("d") or "01"
    hour = match.group("h") or "00"
    minute = match.group("mi") or "00"
    second = match.group("s") or "00"
    stamp = f"{year}-{month}-{day}T{hour}:{minute}:{second}"
    tz = match.group("tz")
    if not tz:
        return stamp
    if tz == "Z":
        return stamp + "Z"
    sign = tz[0]
    digits = tz[1:].replace("'", "")
    if len(digits) == 4 and digits.isdigit():
        return f"{stamp}{sign}{digits[:2]}:{digits[2:]}"
    return stamp


def _pdf_page_count(text: str) -> int | None:
    counts = [int(value) for value in _PAGES_COUNT.findall(text)]
    if counts:
        return max(counts)
    found = _PAGE_OBJECTS.findall(text)
    return len(found) or None
