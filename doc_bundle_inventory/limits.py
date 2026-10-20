"""Resource limits that keep a nested walk from turning into a zip bomb."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_MAX_DEPTH = 6
DEFAULT_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_FILES = 5_000
DEFAULT_MAX_COMPRESSION_RATIO = 100.0
DEFAULT_RATIO_MIN_BYTES = 1 * 1024 * 1024


@dataclass(frozen=True)
class Limits:
    """Caps applied while reading nested archives.

    ``max_depth`` is the number of archives that may be opened, counting the
    root. A nested archive past that depth is listed and not opened.

    The compression-ratio check only applies to members whose declared
    uncompressed size is at least ``ratio_min_bytes``. Tiny files often
    compress extremely well and are not treated as bombs.
    """

    max_depth: int = DEFAULT_MAX_DEPTH
    max_uncompressed_bytes: int = DEFAULT_MAX_UNCOMPRESSED_BYTES
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_files: int = DEFAULT_MAX_FILES
    max_compression_ratio: float = DEFAULT_MAX_COMPRESSION_RATIO
    ratio_min_bytes: int = DEFAULT_RATIO_MIN_BYTES

    def validate(self) -> None:
        if self.max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        if self.max_uncompressed_bytes < 1:
            raise ValueError("max_uncompressed_bytes must be >= 1")
        if self.max_file_bytes < 1:
            raise ValueError("max_file_bytes must be >= 1")
        if self.max_files < 1:
            raise ValueError("max_files must be >= 1")
        if self.max_compression_ratio <= 0:
            raise ValueError("max_compression_ratio must be > 0")
        if self.ratio_min_bytes < 0:
            raise ValueError("ratio_min_bytes must be >= 0")

    def to_dict(self) -> dict[str, int | float]:
        return {
            "max_depth": self.max_depth,
            "max_uncompressed_bytes": self.max_uncompressed_bytes,
            "max_file_bytes": self.max_file_bytes,
            "max_files": self.max_files,
            "max_compression_ratio": self.max_compression_ratio,
            "ratio_min_bytes": self.ratio_min_bytes,
        }
