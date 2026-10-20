"""Command-line entry for doc-bundle-inventory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from doc_bundle_inventory import __version__
from doc_bundle_inventory.errors import InventoryError
from doc_bundle_inventory.inventory import inventory
from doc_bundle_inventory.limits import (
    DEFAULT_MAX_COMPRESSION_RATIO,
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_FILE_BYTES,
    DEFAULT_MAX_FILES,
    DEFAULT_MAX_UNCOMPRESSED_BYTES,
    DEFAULT_RATIO_MIN_BYTES,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-bundle-inventory",
        description=(
            "Inventory a nested document archive (ZIP, optional RAR/7z) "
            "into a JSON manifest of paths, hashes, types, and basic metadata."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("path", help="Path to a .zip archive (.rar/.7z with optional extras)")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Write the manifest to this path instead of stdout",
    )
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-uncompressed-bytes", type=int, default=DEFAULT_MAX_UNCOMPRESSED_BYTES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-compression-ratio", type=float, default=DEFAULT_MAX_COMPRESSION_RATIO)
    parser.add_argument("--ratio-min-bytes", type=int, default=DEFAULT_RATIO_MIN_BYTES)
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indent. Use 0 for a single line",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        manifest = inventory(
            args.path,
            max_depth=args.max_depth,
            max_uncompressed_bytes=args.max_uncompressed_bytes,
            max_file_bytes=args.max_file_bytes,
            max_files=args.max_files,
            max_compression_ratio=args.max_compression_ratio,
            ratio_min_bytes=args.ratio_min_bytes,
        )
    except InventoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    indent = None if args.indent <= 0 else args.indent
    text = json.dumps(manifest, ensure_ascii=False, indent=indent) + "\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    warnings = manifest["stats"]["warnings"]
    if warnings:
        print(f"warnings: {warnings} (see manifest)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
