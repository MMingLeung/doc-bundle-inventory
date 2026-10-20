"""Walk nested ZIP archives, with optional RAR and 7z backends.

Members are read in memory under :class:`~doc_bundle_inventory.limits.Limits`.
Nothing is extracted onto the filesystem, so a rejected ``..`` path cannot
escape the process.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from doc_bundle_inventory.errors import InventoryError, OptionalDependencyError
from doc_bundle_inventory.limits import Limits
from doc_bundle_inventory.metadata import extract_metadata
from doc_bundle_inventory.names import analyze_member_path, recover_zip_filename, version_hints
from doc_bundle_inventory.sniff import detect, ooxml_kind_from_zip, signature_kind

_MESSAGES = {
    "path_traversal": "Rejected member path that contains '..'",
    "absolute_path": "Rejected absolute member path",
    "null_byte": "Rejected member path that contains a null byte",
    "path_too_long": "Rejected member path longer than 4096 characters",
    "empty_path": "Rejected empty member path",
    "max_file_bytes": "Skipped member larger than max_file_bytes",
    "max_uncompressed_bytes": "Skipped member because the uncompressed budget is exhausted",
    "compression_ratio": "Skipped member whose compression ratio looks like a zip bomb",
    "max_files": "Stopped after max_files members",
    "max_depth": "Did not open nested archive because max_depth was reached",
    "encrypted": "Skipped encrypted member",
    "symlink": "Skipped symlink member",
    "bad_member": "Could not read archive member safely",
    "bad_archive": "Could not read nested archive",
    "optional_dependency": "Optional archive support is not installed",
    "metadata_error": "Could not read document metadata",
}


class _Bomb(Exception):
    """The member stream yielded more bytes than its declared size."""


@dataclass
class Member:
    """One archive member, or a directory entry, before JSON rendering."""

    containers: tuple[str, ...]
    member_path: str
    logical_path: str
    kind: str
    file_type: str
    mime: str | None
    size: int | None
    sha256: str | None
    name_encoding: str
    version_hints: list[str]
    metadata: dict | None
    duplicate_group: str | None = None


@dataclass
class WalkState:
    limits: Limits
    members: list[Member] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    seen: int = 0
    uncompressed: int = 0
    stop: bool = False


def collect(path: Path, limits: Limits) -> WalkState:
    """Walk the archive at ``path`` and return members plus warnings."""

    if not path.is_file():
        raise InventoryError(f"not a file: {path}")
    with path.open("rb") as handle:
        header = handle.read(8)
    kind = signature_kind(header)
    if kind is None:
        raise InventoryError(
            "unsupported file: expected a .zip archive "
            "(.rar and .7z are optional extras and still need a matching signature)"
        )
    state = WalkState(limits=limits)
    containers = (path.name,)
    if kind == "zip":
        _walk_zip_path(path, containers, depth=1, state=state, is_root=True)
    elif kind == "rar":
        _walk_rar_path(path, containers, depth=1, state=state, origin=path.name, is_root=True)
    else:
        _walk_7z_path(path, containers, depth=1, state=state, origin=path.name, is_root=True)
    return state


def _logical(containers: tuple[str, ...], member_path: str) -> str:
    return "!/".join((*containers, member_path))


def _warn(state: WalkState, code: str, path: str, message: str | None = None) -> None:
    state.warnings.append(
        {
            "code": code,
            "path": path,
            "message": message or _MESSAGES.get(code, code),
        }
    )


def _reserve(state: WalkState, path: str) -> bool:
    if state.stop:
        return False
    if state.seen >= state.limits.max_files:
        state.stop = True
        _warn(state, "max_files", path)
        return False
    state.seen += 1
    return True


def _ratio_too_high(file_size: int, compress_size: int, limits: Limits) -> bool:
    if file_size < limits.ratio_min_bytes:
        return False
    if compress_size <= 0:
        return True
    return (file_size / compress_size) > limits.max_compression_ratio


def _read_capped(source, limit: int) -> bytes:
    buf = bytearray()
    while len(buf) <= limit:
        block = source.read(min(65536, limit - len(buf) + 1))
        if not block:
            break
        buf.extend(block)
        if len(buf) > limit:
            raise _Bomb("read exceeded declared uncompressed size")
    return bytes(buf)


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    unix_mode = info.external_attr >> 16
    return (unix_mode & 0o170000) == 0o120000


def _consider(
    state: WalkState,
    *,
    containers: tuple[str, ...],
    depth: int,
    raw_name: str,
    recovered_name: str,
    name_encoding: str,
    is_dir: bool,
    is_encrypted: bool,
    is_link: bool,
    declared_size: int,
    compress_size: int,
    read: Callable[[], bytes] | None,
) -> None:
    display = recovered_name or raw_name
    logical_attempt = _logical(containers, display)
    if not _reserve(state, logical_attempt):
        return

    normalized, error = analyze_member_path(recovered_name)
    if error is None and raw_name != recovered_name:
        _raw_norm, raw_error = analyze_member_path(raw_name)
        error = raw_error
    if is_dir and error == "empty_path":
        return
    if error:
        _warn(state, error, logical_attempt)
        return
    assert normalized is not None
    logical = _logical(containers, normalized)

    if is_link:
        _warn(state, "symlink", logical)
        return
    if is_encrypted:
        _warn(state, "encrypted", logical)
        return
    if is_dir:
        state.members.append(
            Member(
                containers=containers,
                member_path=normalized,
                logical_path=logical,
                kind="directory",
                file_type="directory",
                mime=None,
                size=0,
                sha256=None,
                name_encoding=name_encoding,
                version_hints=[],
                metadata=None,
            )
        )
        return

    if declared_size > state.limits.max_file_bytes:
        _warn(state, "max_file_bytes", logical)
        return
    if state.uncompressed + max(declared_size, 0) > state.limits.max_uncompressed_bytes:
        _warn(state, "max_uncompressed_bytes", logical)
        return
    if _ratio_too_high(declared_size, compress_size, state.limits):
        _warn(state, "compression_ratio", logical)
        return
    if read is None:
        _warn(state, "bad_member", logical)
        return

    try:
        data = read()
    except _Bomb:
        _warn(state, "compression_ratio", logical, "Member stream exceeded the declared size cap")
        return
    except Exception as exc:  # noqa: BLE001 — a bad member should not abort the walk
        _warn(state, "bad_member", logical, f"Could not read archive member ({type(exc).__name__})")
        return

    if len(data) > state.limits.max_file_bytes:
        _warn(state, "max_file_bytes", logical)
        return
    state.uncompressed += len(data)

    detected = detect(normalized, data)
    kind = "archive" if detected.open_as else "file"
    hints = version_hints(normalized)
    meta = None
    if detected.file_type in {"pdf", "docx"}:
        try:
            meta = extract_metadata(detected.file_type, data)
        except Exception:  # noqa: BLE001 — metadata is best-effort
            _warn(state, "metadata_error", logical)
            meta = None

    state.members.append(
        Member(
            containers=containers,
            member_path=normalized,
            logical_path=logical,
            kind=kind,
            file_type=detected.file_type,
            mime=detected.mime,
            size=len(data),
            sha256=_sha256(data),
            name_encoding=name_encoding,
            version_hints=hints,
            metadata=meta,
        )
    )
    if detected.open_as:
        _open_nested(
            detected.open_as,
            data,
            containers + (normalized,),
            depth + 1,
            state,
            logical,
        )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _open_nested(
    file_type: str,
    data: bytes,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
    logical: str,
) -> None:
    if state.stop:
        return
    if depth > state.limits.max_depth:
        _warn(state, "max_depth", logical)
        return
    try:
        if file_type == "zip":
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                _walk_open_zip(zf, containers, depth, state)
        elif file_type == "rar":
            _walk_rar_bytes(data, containers, depth, state, logical, is_root=False)
        else:
            _walk_7z_bytes(data, containers, depth, state, logical, is_root=False)
    except InventoryError as exc:
        _warn(state, "optional_dependency", logical, str(exc))
    except zipfile.BadZipFile:
        _warn(state, "bad_archive", logical)
    except Exception as exc:  # noqa: BLE001
        _warn(state, "bad_archive", logical, f"Could not read nested archive ({type(exc).__name__})")


def _walk_zip_path(
    path: Path,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
    *,
    is_root: bool,
) -> None:
    try:
        with zipfile.ZipFile(path) as zf:
            if is_root:
                office = ooxml_kind_from_zip(zf)
                if office:
                    raise InventoryError(
                        f"this is a .{office} document, not a document bundle; "
                        "pass the archive that contains it"
                    )
            _walk_open_zip(zf, containers, depth, state)
    except InventoryError:
        raise
    except zipfile.BadZipFile as exc:
        if is_root:
            raise InventoryError(f"cannot read zip archive: {exc}") from exc
        _warn(state, "bad_archive", "!/".join(containers))


def _walk_open_zip(
    zf: zipfile.ZipFile,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
) -> None:
    # Default zipfile decoding (CP437 when bit 11 is clear) is required so
    # GBK names can be recovered. Do not pass metadata_encoding here.
    for info in zf.infolist():
        if state.stop:
            return
        recovered, encoding = recover_zip_filename(info.filename, info.flag_bits)
        limit = min(info.file_size, state.limits.max_file_bytes)

        def _read(info: zipfile.ZipInfo = info, limit: int = limit) -> bytes:
            with zf.open(info, "r") as source:
                return _read_capped(source, limit)

        _consider(
            state,
            containers=containers,
            depth=depth,
            raw_name=info.filename,
            recovered_name=recovered,
            name_encoding=encoding,
            is_dir=info.is_dir(),
            is_encrypted=bool(info.flag_bits & 0x1),
            is_link=_is_zip_symlink(info),
            declared_size=info.file_size,
            compress_size=info.compress_size,
            read=None if info.is_dir() else _read,
        )


def _walk_rar_path(
    path: Path,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
    origin: str,
    *,
    is_root: bool,
) -> None:
    rarfile = _import_rarfile(is_root=is_root, origin=origin, state=state)
    if rarfile is None:
        return
    try:
        archive = rarfile.RarFile(str(path))
    except Exception as exc:  # noqa: BLE001
        _fail_archive(is_root, origin, state, exc, label="rar")
        return
    try:
        _walk_rar_open(archive, containers, depth, state)
    finally:
        archive.close()


def _walk_rar_bytes(
    data: bytes,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
    origin: str,
    *,
    is_root: bool,
) -> None:
    rarfile = _import_rarfile(is_root=is_root, origin=origin, state=state)
    if rarfile is None:
        return
    # unrar reads a real path; the logical name stays in ``containers``.
    handle = tempfile.NamedTemporaryFile(suffix=".rar", delete=False)
    try:
        handle.write(data)
        handle.close()
        try:
            archive = rarfile.RarFile(handle.name)
        except Exception as exc:  # noqa: BLE001
            _fail_archive(is_root, origin, state, exc, label="rar")
            return
        try:
            _walk_rar_open(archive, containers, depth, state)
        finally:
            archive.close()
    finally:
        os.unlink(handle.name)


def _walk_rar_open(archive, containers: tuple[str, ...], depth: int, state: WalkState) -> None:
    for info in archive.infolist():
        if state.stop:
            return
        name = getattr(info, "filename", "") or ""
        is_dir = bool(info.isdir()) if hasattr(info, "isdir") else name.endswith("/")
        needs_password = getattr(info, "needs_password", False)
        encrypted = bool(needs_password() if callable(needs_password) else needs_password)
        file_size = int(getattr(info, "file_size", 0) or 0)
        compress_size = int(getattr(info, "compress_size", 0) or 0)

        def _read(info=info, file_size: int = file_size) -> bytes:
            payload = archive.read(info)
            if len(payload) > file_size and file_size:
                raise _Bomb("rar member larger than declared size")
            return payload

        _consider(
            state,
            containers=containers,
            depth=depth,
            raw_name=name,
            recovered_name=name,
            name_encoding="rar",
            is_dir=is_dir,
            is_encrypted=encrypted,
            is_link=False,
            declared_size=file_size,
            compress_size=compress_size,
            read=None if is_dir else _read,
        )


def _walk_7z_path(
    path: Path,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
    origin: str,
    *,
    is_root: bool,
) -> None:
    py7zr = _import_py7zr(is_root=is_root, origin=origin, state=state)
    if py7zr is None:
        return
    try:
        archive = py7zr.SevenZipFile(path, mode="r")
    except Exception as exc:  # noqa: BLE001
        _fail_archive(is_root, origin, state, exc, label="7z")
        return
    with archive:
        _walk_7z_open(archive, containers, depth, state)


def _walk_7z_bytes(
    data: bytes,
    containers: tuple[str, ...],
    depth: int,
    state: WalkState,
    origin: str,
    *,
    is_root: bool,
) -> None:
    py7zr = _import_py7zr(is_root=is_root, origin=origin, state=state)
    if py7zr is None:
        return
    try:
        archive = py7zr.SevenZipFile(io.BytesIO(data), mode="r")
    except Exception as exc:  # noqa: BLE001
        _fail_archive(is_root, origin, state, exc, label="7z")
        return
    with archive:
        _walk_7z_open(archive, containers, depth, state)


def _walk_7z_open(archive, containers: tuple[str, ...], depth: int, state: WalkState) -> None:
    for info in list(archive.list()):
        if state.stop:
            return
        name = getattr(info, "filename", "") or ""
        is_dir = bool(getattr(info, "is_directory", False)) or name.endswith("/")
        file_size = int(getattr(info, "uncompressed", 0) or 0)
        compress_size = int(getattr(info, "compressed", 0) or 0)

        def _read(name: str = name, file_size: int = file_size) -> bytes:
            payloads = archive.read(targets=[name]) or {}
            stream = payloads.get(name)
            if stream is None:
                return b""
            data = stream.read() if hasattr(stream, "read") else bytes(stream)
            if file_size and len(data) > file_size:
                raise _Bomb("7z member larger than declared size")
            return data

        _consider(
            state,
            containers=containers,
            depth=depth,
            raw_name=name,
            recovered_name=name,
            name_encoding="utf-8",
            is_dir=is_dir,
            is_encrypted=False,
            is_link=False,
            declared_size=0 if is_dir else file_size,
            compress_size=0 if is_dir else compress_size,
            read=None if is_dir else _read,
        )


def _import_rarfile(*, is_root: bool, origin: str, state: WalkState):
    try:
        import rarfile
    except ImportError as exc:
        message = (
            "RAR support is not installed. "
            "pip install 'doc-bundle-inventory[rar]' and provide an unrar binary"
        )
        if is_root:
            raise OptionalDependencyError(message) from exc
        _warn(state, "optional_dependency", origin, message)
        return None
    return rarfile


def _import_py7zr(*, is_root: bool, origin: str, state: WalkState):
    try:
        import py7zr
    except ImportError as exc:
        message = "7z support is not installed. pip install 'doc-bundle-inventory[py7zr]'"
        if is_root:
            raise OptionalDependencyError(message) from exc
        _warn(state, "optional_dependency", origin, message)
        return None
    return py7zr


def _fail_archive(is_root: bool, origin: str, state: WalkState, exc: Exception, *, label: str) -> None:
    if is_root:
        raise InventoryError(f"cannot read {label} archive: {exc}") from exc
    _warn(state, "bad_archive", origin, f"Could not read nested {label} archive ({type(exc).__name__})")
