#!/usr/bin/env python3
"""Placeholder entrypoint for a future Mimics review-package exporter."""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("working_dir", help="Path to the Mimics export working directory.")
    args = parser.parse_args()
    print(
        "Mimics adapter scaffold only. "
        f"Manual export review is still required for now: {args.working_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
