#!/usr/bin/env python3
"""Template for an L4 dataset importer.

Copy this file before editing it. The template intentionally does not guess any
dataset semantics. Implement discover_dataset() for one concrete dataset, then
keep the output contract unchanged:

- requests/*.json: case_package_request.v1
- reports/import_summary.json
- reports/import_issues.csv
- reports/importer_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ISSUE_COLUMNS = [
    "severity",
    "code",
    "case_hint",
    "image_hint",
    "label_hint",
    "path",
    "message",
    "required_action",
    "disposition",
    "evidence",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_revision(repo_root: Path) -> str:
    try:
        value = subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"
    return "git:" + value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_issues(path: Path, issues: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ISSUE_COLUMNS)
        writer.writeheader()
        for issue in issues:
            writer.writerow({column: issue.get(column, "") for column in ISSUE_COLUMNS})


def issue(
    *,
    severity: str,
    code: str,
    message: str,
    required_action: str,
    disposition: str,
    case_hint: str = "",
    image_hint: str = "",
    label_hint: str = "",
    path: str = "",
    evidence: str = "",
) -> dict[str, str]:
    return {
        "severity": severity,
        "code": code,
        "case_hint": case_hint,
        "image_hint": image_hint,
        "label_hint": label_hint,
        "path": path,
        "message": message,
        "required_action": required_action,
        "disposition": disposition,
        "evidence": evidence,
    }


def discover_dataset(source_root: Path, args: argparse.Namespace) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Return standard request dictionaries and issue dictionaries.

    Replace this function for a real dataset. Keep these rules:

    - Create a request only when image-label pairing, organ semantics, and
      geometry evidence are explicit enough.
    - Put uncertain cases into issues instead of guessing.
    - Use stable case_id, study_id, image_id, target_id, and leakage_group_id.
    - Use label_map for multilabel masks and organ for per-organ masks.
    """

    return [], [
        issue(
            severity="error",
            code="importer_not_implemented",
            path=str(source_root),
            message="custom importer template has not implemented dataset-specific discovery",
            required_action="copy the template and implement discover_dataset() for one dataset",
            disposition="quarantined",
            evidence="template default",
        )
    ]


def write_requests(requests_dir: Path, requests: list[dict[str, Any]]) -> list[str]:
    written: list[str] = []
    requests_dir.mkdir(parents=True, exist_ok=True)
    for request in requests:
        case_id = str(request["case_id"])
        path = requests_dir / f"{case_id}.json"
        write_json(path, request)
        written.append(str(path))
    return written


def build_summary(
    *,
    args: argparse.Namespace,
    requests: list[dict[str, Any]],
    request_paths: list[str],
    issues: list[dict[str, str]],
) -> dict[str, Any]:
    issue_counts = {
        "error": sum(1 for item in issues if item.get("severity") == "error"),
        "warning": sum(1 for item in issues if item.get("severity") == "warning"),
        "info": sum(1 for item in issues if item.get("severity") == "info"),
    }
    if issue_counts["error"]:
        status = "blocked"
    elif issue_counts["warning"]:
        status = "passed_with_warnings"
    else:
        status = "passed"
    return {
        "schema_version": "custom_importer_summary.v1",
        "dataset_id": args.dataset_id,
        "run_id": args.run_id,
        "created_at": utc_now(),
        "status": status,
        "request_count": len(requests),
        "case_count": len({request["case_id"] for request in requests}),
        "image_set_count": sum(len(request.get("image_sets", [])) for request in requests),
        "initial_label_count": sum(len(request.get("initial_labels", [])) for request in requests),
        "issue_counts": issue_counts,
        "requests": request_paths,
        "requests_dir": "requests",
        "issues_csv": "reports/import_issues.csv",
        "manifest": "reports/importer_manifest.json",
        "next_command": "sp package create-many requests dataset_package --registry registry --continue-on-error",
    }


def build_manifest(args: argparse.Namespace, source_root: Path, output_root: Path) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    return {
        "schema_version": "custom_importer_manifest.v1",
        "dataset_id": args.dataset_id,
        "run_id": args.run_id,
        "created_at": utc_now(),
        "importer_name": args.importer_name,
        "importer_version": args.importer_version,
        "code_revision": git_revision(repo_root),
        "source_root": str(source_root),
        "output_root": str(output_root),
        "config_path": str(args.config.resolve()) if args.config else "",
        "request_schema_version": "case_package_request.v1",
        "platform_commit": git_revision(repo_root),
        "notes": args.notes or "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Template L4 dataset importer")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--config", type=Path)
    parser.add_argument("--importer-name", default="custom_dataset_importer")
    parser.add_argument("--importer-version", default="0.1.0")
    parser.add_argument("--notes", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    if not source_root.is_dir():
        raise SystemExit(f"source_root is not a directory: {source_root}")

    requests, issues = discover_dataset(source_root, args)
    request_paths = [] if args.dry_run else write_requests(output_root / "requests", requests)
    summary = build_summary(args=args, requests=requests, request_paths=request_paths, issues=issues)
    manifest = build_manifest(args, source_root, output_root)

    if not args.dry_run:
        write_issues(output_root / "reports" / "import_issues.csv", issues)
        write_json(output_root / "reports" / "import_summary.json", summary)
        write_json(output_root / "reports" / "importer_manifest.json", manifest)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 2 if summary["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
