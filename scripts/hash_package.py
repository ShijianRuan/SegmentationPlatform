#!/usr/bin/env python3
"""Generate SHA-256 checksums for a package directory."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


DEFAULT_OUTPUT_NAME = "checksums.sha256"


def iter_files(root: Path, output_name: str) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == output_name:
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_checksum_text(root: Path, output_name: str = DEFAULT_OUTPUT_NAME) -> str:
    lines = []
    for path in iter_files(root, output_name):
        rel = path.relative_to(root).as_posix()
        lines.append(f"{sha256_file(path)}  {rel}")
    return "\n".join(lines) + ("\n" if lines else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--output-name", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--write", action="store_true", help="Write checksums.sha256 into the package directory.")
    args = parser.parse_args()

    root = args.package_dir.resolve()
    if not root.is_dir():
        parser.error(f"package_dir is not a directory: {root}")

    text = build_checksum_text(root, args.output_name)
    if args.write:
        output_path = root / args.output_name
        output_path.write_text(text, encoding="utf-8")
        print(f"wrote {output_path}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
