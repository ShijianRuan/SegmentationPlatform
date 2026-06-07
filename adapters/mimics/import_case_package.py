#!/usr/bin/env python3
"""Placeholder entrypoint for a future Mimics case-package importer."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", help="Path to a Case Package directory.")
    args = parser.parse_args()
    print(
        "Mimics adapter scaffold only. "
        f"Manual import is still required for now: {args.package_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
