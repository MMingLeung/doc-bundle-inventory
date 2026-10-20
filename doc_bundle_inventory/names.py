"""Member-path checks, ZIP filename repair, and filename version hints."""

from __future__ import annotations

import re

# ZIP general-purpose bit 11: filename and comment are UTF-8.
UTF8_FLAG = 0x800

_DRIVE = re.compile(r"^[A-Za-z]:")
_CJK = re.compile(r"[\u3400-\u9fff]")

# Longer tags first so they win when we scan left to right.
_CN_TAGS = ("送审稿", "修订稿", "最终版", "修订版", "终稿", "定稿", "初稿", "草稿")
_CN_EDITION = re.compile(r"第\s*([0-9]{1,3})\s*版")
_VERSION = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:version|ver|v)[\s._-]*(\d+(?:\.\d+){0,3})(?!\d)"
)
_EN_TAGS = re.compile(r"(?i)(?<![A-Za-z])(final|draft)(?![A-Za-z])")


def analyze_member_path(name: str) -> tuple[str | None, str | None]:
    """Return ``(normalized_relative_posix, error_code)``.

    Rejects absolute paths, drive paths, null bytes, and any ``..`` segment.
    ``.`` and empty segments are dropped. The returned path is safe to use as
    a logical name; this library never joins it onto the filesystem.
    """

    if name is None:
        return None, "empty_path"
    if "\x00" in name:
        return None, "null_byte"
    if len(name) > 4096:
        return None, "path_too_long"

    translated = name.replace("\\", "/")
    if translated.startswith("/"):
        return None, "absolute_path"
    if _DRIVE.match(translated):
        return None, "absolute_path"

    parts: list[str] = []
    for part in translated.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None, "path_traversal"
        parts.append(part)
    if not parts:
        return None, "empty_path"
    return "/".join(parts), None


def recover_zip_filename(filename: str, flag_bits: int) -> tuple[str, str]:
    """Repair a ZIP member name and return ``(name, encoding)``.

    The ZIP spec stores UTF-8 names when bit 11 is set. Otherwise Python's
    ``zipfile`` decodes the bytes as CP437. Chinese Windows tools often write
    GBK bytes without that bit, which shows up as mojibake. We reverse the
    CP437 decode and try UTF-8, then GB18030 (a superset of GBK). The
    alternative is kept only when it scores as more readable (typically
    because it contains CJK characters).
    """

    if flag_bits & UTF8_FLAG:
        return filename, "utf-8"
    try:
        raw = filename.encode("cp437")
    except UnicodeEncodeError:
        return filename, "cp437"

    candidates: list[tuple[str, str]] = []
    for encoding in ("utf-8", "gb18030"):
        try:
            candidates.append((encoding, raw.decode(encoding)))
        except UnicodeDecodeError:
            continue
    if not candidates:
        return filename, "cp437"

    def score(text: str) -> int:
        cjk = len(_CJK.findall(text))
        bad = text.count("\ufffd")
        bad += sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\r\n")
        return cjk * 10 - bad * 20

    best_encoding, best_text = max(
        candidates,
        key=lambda item: (score(item[1]), 1 if item[0] == "utf-8" else 0),
    )
    if score(best_text) > score(filename):
        return best_text, best_encoding
    return filename, "cp437"


def version_hints(filename: str) -> list[str]:
    """Pull obvious version or draft markers out of a single filename.

    Looks at the basename only. Examples: ``v1.2``, ``version 3``, ``终稿``,
    ``第2版``, ``final``, ``draft``.
    """

    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    hints: list[str] = []

    def add(value: str) -> None:
        if value and value not in hints:
            hints.append(value)

    for match in _VERSION.finditer(base):
        add("v" + match.group(1))
    for match in _CN_EDITION.finditer(base):
        add(f"第{match.group(1)}版")
    for tag in _CN_TAGS:
        if tag in base:
            add(tag)
    for match in _EN_TAGS.finditer(base):
        add(match.group(1).lower())
    return hints
