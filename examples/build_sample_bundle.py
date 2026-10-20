#!/usr/bin/env python3
"""Build examples/sample_bundle/bundle.zip, a small nested demo archive.

The outer ZIP stores ``说明.txt`` as GBK without the UTF-8 flag, which is how
many Chinese Windows tools write names. Everything else is standard UTF-8.
Run from the repo root:

    python examples/build_sample_bundle.py
"""

from __future__ import annotations

import argparse
import io
import struct
import zipfile
import zlib
from pathlib import Path

STAMP = (2024, 6, 1, 9, 0, 0)

TEXT_NOTE = "这是一个嵌套压缩包示例。\n"
TEXT_V1 = "版本一：范围说明。\n"
TEXT_V12 = "版本 1.2 终稿：范围已确认。\n"
TEXT_INNER = "内层附件备注。\n"

AUTHOR = "李明"
DOCX_TITLE = "示例合同"
PDF_TITLE = "封面"
MODIFIED = "2024-06-01T09:00:00Z"
PDF_MODIFIED = "D:20240601090000Z"

ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROOT / "sample_bundle" / "bundle.zip"


class EncodedZipInfo(zipfile.ZipInfo):
    """ZIP member whose filename bytes are encoded without the UTF-8 flag."""

    def __init__(self, filename: str, encoding: str, date_time: tuple[int, ...] = STAMP):
        super().__init__(filename=filename, date_time=date_time)
        self._raw_encoding = encoding

    def _encodeFilenameFlags(self):  # noqa: N802 — matches zipfile's private hook
        return self.filename.encode(self._raw_encoding), self.flag_bits & ~0x800


def add_file(
    archive: zipfile.ZipFile,
    name: str,
    data: bytes,
    *,
    encoding: str | None = None,
) -> None:
    info: zipfile.ZipInfo
    if encoding:
        info = EncodedZipInfo(name, encoding)
    else:
        info = zipfile.ZipInfo(filename=name, date_time=STAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_docx(
    *,
    author: str = AUTHOR,
    title: str = DOCX_TITLE,
    modified: str = MODIFIED,
    pages: int = 2,
    body: str = "示例合同正文",
) -> bytes:
    """Minimal Office Open XML document with core and app properties."""

    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""
    rels = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{xml_escape(body)}</w:t></w:r></w:p></w:body>
</w:document>
"""
    core = f"""<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{xml_escape(title)}</dc:title>
  <dc:creator>{xml_escape(author)}</dc:creator>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{xml_escape(modified)}</dcterms:modified>
</cp:coreProperties>
"""
    app = f"""<?xml version="1.0" encoding="UTF-8"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">
  <Pages>{pages}</Pages>
</Properties>
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as docx:
        add_file(docx, "[Content_Types].xml", content_types.encode("utf-8"))
        add_file(docx, "_rels/.rels", rels.encode("utf-8"))
        add_file(docx, "word/document.xml", document.encode("utf-8"))
        add_file(docx, "docProps/core.xml", core.encode("utf-8"))
        add_file(docx, "docProps/app.xml", app.encode("utf-8"))
    return buf.getvalue()


def _pdf_escape(text: str) -> bytes:
    out = bytearray()
    for byte in text.encode("utf-8"):
        if byte in (0x28, 0x29, 0x5C):
            out.extend((0x5C, byte))
        else:
            out.append(byte)
    return bytes(out)


def build_pdf(
    *,
    author: str = AUTHOR,
    title: str = PDF_TITLE,
    modified: str = PDF_MODIFIED,
) -> bytes:
    """One-page PDF with an Info dictionary. Strings are UTF-8 literals."""

    stream = b"BT /F1 24 Tf 72 720 Td (Cover) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << >> >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream",
        b"<< /Title ("
        + _pdf_escape(title)
        + b") /Author ("
        + _pdf_escape(author)
        + b") /ModDate ("
        + modified.encode("ascii")
        + b") >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode("ascii"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref_at = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 5 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def build_png() -> bytes:
    """1x1 red PNG."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw_scanline = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw_scanline, 9))
        + chunk(b"IEND", b"")
    )


def build_inner_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as inner:
        add_file(inner, "附件/备注.txt", TEXT_INNER.encode("utf-8"))
        add_file(inner, "附件/合同_终稿.docx", build_docx())
        add_file(inner, "附件/封面.pdf", build_pdf())
    return buf.getvalue()


def build_sample(output: Path = DEFAULT_OUTPUT) -> Path:
    """Write the nested demo ZIP and return its path."""

    output.parent.mkdir(parents=True, exist_ok=True)
    note = TEXT_NOTE.encode("utf-8")
    v1 = TEXT_V1.encode("utf-8")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as outer:
        add_file(outer, "说明.txt", note, encoding="gbk")
        add_file(outer, "预览.png", build_png())
        add_file(outer, "报告/项目说明_v1.0.txt", v1)
        add_file(outer, "报告/项目说明_v1.2_终稿.txt", TEXT_V12.encode("utf-8"))
        add_file(outer, "报告/副本/项目说明_v1.0.txt", v1)
        add_file(outer, "报告/说明_副本.txt", note)
        add_file(outer, "报告/inner.zip", build_inner_zip())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write the nested demo ZIP.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination ZIP path",
    )
    args = parser.parse_args(argv)
    path = build_sample(args.output)
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
