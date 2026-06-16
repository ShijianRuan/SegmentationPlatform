from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from segplatform.adapters.mimics.doctor import doctor
from segplatform.adapters.mimics.finalize import finalize_case
from segplatform.adapters.mimics.launcher import open_case
from segplatform.adapters.mimics.prepare import prepare_case
from segplatform.adapters.mimics.probes import evaluate_probe, run_probe
from segplatform.case_packages import create_case_package, validate_case_package, validate_registry_record
from segplatform.common import load_data
from segplatform.errors import SegPlatformError
from segplatform.ingest import build_case_package_requests, scan_source
from segplatform.registry import FileRegistry
from segplatform.snapshots import create_snapshot, validate_snapshot


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _split_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(item.strip() for item in value.split(",") if item.strip())
    return result


def _request_files(root: Path) -> list[Path]:
    return sorted(
        path
        for pattern in ("*.yaml", "*.yml", "*.json")
        for path in root.glob(pattern)
        if path.name != "request_batch_summary.json"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sp", description="SegmentationPlatform offline workflow")
    subparsers = parser.add_subparsers(dest="domain", required=True)

    ingest = subparsers.add_parser("ingest", help="Discover source data and generate package requests")
    ingest_sub = ingest.add_subparsers(dest="action", required=True)
    ingest_scan = ingest_sub.add_parser("scan")
    ingest_scan.add_argument("source_root", type=Path)
    ingest_scan.add_argument("--output", type=Path, required=True)
    ingest_build = ingest_sub.add_parser("build-requests")
    ingest_build.add_argument("scan", type=Path)
    ingest_build.add_argument("output_dir", type=Path)
    ingest_build.add_argument("--organs", nargs="+", required=True)
    ingest_build.add_argument("--import-batch", required=True)
    ingest_build.add_argument("--assignee")
    ingest_build.add_argument("--tool", default="mimics")
    ingest_build.add_argument("--source-type", default="dicom_scan")
    ingest_build.add_argument("--deidentification-status", default="verified")
    ingest_build.add_argument("--governance-profile", default="import_scan_profile")
    ingest_build.add_argument("--governance-profile-version", default="1")

    package = subparsers.add_parser("package", help="Create and validate Case Packages")
    package_sub = package.add_subparsers(dest="action", required=True)
    package_create = package_sub.add_parser("create")
    package_create.add_argument("request", type=Path)
    package_create.add_argument("output_root", type=Path)
    package_create.add_argument("--registry", type=Path)
    package_create.add_argument("--overwrite", action="store_true")
    package_create_many = package_sub.add_parser("create-many")
    package_create_many.add_argument("request_dir", type=Path)
    package_create_many.add_argument("output_root", type=Path)
    package_create_many.add_argument("--registry", type=Path)
    package_create_many.add_argument("--overwrite", action="store_true")
    package_create_many.add_argument("--continue-on-error", action="store_true")
    package_validate = package_sub.add_parser("validate")
    package_validate.add_argument("case_root", type=Path)

    mimics = subparsers.add_parser("mimics", help="Mimics Research 21 adapter")
    mimics_sub = mimics.add_subparsers(dest="action", required=True)
    mimics_doctor = mimics_sub.add_parser("doctor")
    mimics_doctor.add_argument("--config", type=Path, required=True)
    mimics_doctor.add_argument("--run-diagnostics", action="store_true")
    mimics_prepare = mimics_sub.add_parser("prepare")
    mimics_prepare.add_argument("case_root", type=Path)
    mimics_prepare.add_argument("--config", type=Path, required=True)
    mimics_prepare.add_argument("--rebuild-workspace", action="store_true")
    mimics_open = mimics_sub.add_parser("open")
    mimics_open.add_argument("case_root", type=Path)
    mimics_open.add_argument("--config", type=Path, required=True)
    mimics_open.add_argument("--dry-run", action="store_true")
    mimics_open.add_argument("--wait", action="store_true")
    mimics_open.add_argument("--registry", type=Path)
    mimics_finalize = mimics_sub.add_parser("finalize")
    mimics_finalize.add_argument("case_root", type=Path)
    mimics_finalize.add_argument("--config", type=Path, required=True)
    mimics_finalize.add_argument("--registry", type=Path, required=True)
    mimics_probe_run = mimics_sub.add_parser("probe-run")
    mimics_probe_run.add_argument("case_root", type=Path)
    mimics_probe_run.add_argument("--config", type=Path, required=True)
    mimics_probe_run.add_argument("--output", type=Path)
    mimics_probe_run.add_argument("--dry-run", action="store_true")
    mimics_probe_run.add_argument("--no-wait", action="store_true")
    mimics_probe_evaluate = mimics_sub.add_parser("probe-evaluate")
    mimics_probe_evaluate.add_argument("case_root", type=Path)
    mimics_probe_evaluate.add_argument("evidence", type=Path)
    mimics_probe_evaluate.add_argument("--config", type=Path, required=True)
    mimics_probe_evaluate.add_argument("--output-config", type=Path, required=True)
    mimics_probe_evaluate.add_argument("--tolerance-mm", type=float, default=1e-3)

    review = subparsers.add_parser("review", help="Inspect offline review tasks")
    review_sub = review.add_subparsers(dest="action", required=True)
    review_status = review_sub.add_parser("status")
    review_status.add_argument("--registry", type=Path, required=True)
    review_status.add_argument("--review-id")

    registry = subparsers.add_parser("registry", help="Validate registry records")
    registry_sub = registry.add_subparsers(dest="action", required=True)
    registry_validate = registry_sub.add_parser("validate")
    registry_validate.add_argument("record", type=Path)
    registry_validate.add_argument("--schema", required=True)
    registry_rebuild = registry_sub.add_parser("rebuild-index")
    registry_rebuild.add_argument("registry_root", type=Path)

    snapshot = subparsers.add_parser("snapshot", help="Create the immutable pre-training dataset snapshot")
    snapshot_sub = snapshot.add_subparsers(dest="action", required=True)
    snapshot_create = snapshot_sub.add_parser("create")
    snapshot_create.add_argument("request", type=Path)
    snapshot_create.add_argument("--registry", type=Path, required=True)
    snapshot_validate = snapshot_sub.add_parser("validate")
    snapshot_validate.add_argument("snapshot", type=Path)
    return parser


def run(args: argparse.Namespace) -> int:
    if args.domain == "ingest" and args.action == "scan":
        report = scan_source(args.source_root)
        from segplatform.common import write_json

        write_json(args.output, report)
        print_json({"status": "scanned", "output": str(args.output), **report["summary"]})
    elif args.domain == "ingest" and args.action == "build-requests":
        print_json(
            build_case_package_requests(
                args.scan,
                args.output_dir,
                organs=_split_values(args.organs),
                import_batch=args.import_batch,
                assignee=args.assignee,
                tool=args.tool,
                source_type=args.source_type,
                deidentification_status=args.deidentification_status,
                governance_profile=args.governance_profile,
                governance_profile_version=args.governance_profile_version,
            )
        )
    elif args.domain == "package" and args.action == "create":
        path = create_case_package(args.request, args.output_root, registry_root=args.registry, overwrite=args.overwrite)
        print_json({"status": "created", "case_root": str(path)})
    elif args.domain == "package" and args.action == "create-many":
        results = []
        had_error = False
        for request_path in _request_files(args.request_dir):
            try:
                case_root = create_case_package(
                    request_path,
                    args.output_root,
                    registry_root=args.registry,
                    overwrite=args.overwrite,
                )
                results.append({"request": str(request_path), "status": "created", "case_root": str(case_root)})
            except Exception as error:
                had_error = True
                results.append({"request": str(request_path), "status": "failed", "error": str(error)})
                if not args.continue_on_error:
                    break
        print_json({"status": "failed" if had_error else "created", "results": results})
        if had_error:
            return 2
    elif args.domain == "package" and args.action == "validate":
        report = validate_case_package(args.case_root)
        print_json(report)
        return 0 if report["status"] == "passed" else 2
    elif args.domain == "mimics" and args.action == "doctor":
        report = doctor(args.config, run_diagnostics=args.run_diagnostics)
        print_json(report)
        return 0 if report["status"] == "ready" else 2
    elif args.domain == "mimics" and args.action == "prepare":
        path = prepare_case(args.case_root, args.config, rebuild_workspace=args.rebuild_workspace)
        print_json({"status": "prepared", "runtime_manifest": str(path)})
    elif args.domain == "mimics" and args.action == "open":
        print_json(
            open_case(
                args.case_root,
                args.config,
                dry_run=args.dry_run,
                wait=args.wait,
                registry_root=args.registry,
            )
        )
    elif args.domain == "mimics" and args.action == "finalize":
        print_json(finalize_case(args.case_root, args.config, args.registry))
    elif args.domain == "mimics" and args.action == "probe-run":
        result = run_probe(
            args.case_root,
            args.config,
            output_dir=args.output,
            dry_run=args.dry_run,
            wait=not args.no_wait,
        )
        print_json(result)
        if result.get("returncode") not in (None, 0):
            return 2
    elif args.domain == "mimics" and args.action == "probe-evaluate":
        result = evaluate_probe(
            args.case_root,
            args.evidence,
            args.config,
            args.output_config,
            tolerance_mm=args.tolerance_mm,
        )
        print_json(result)
        return 0 if result["status"] == "passed" else 2
    elif args.domain == "review" and args.action == "status":
        registry = FileRegistry(args.registry)
        if args.review_id:
            print_json(registry.get("reviews", args.review_id))
        else:
            print_json(registry.list("reviews"))
    elif args.domain == "registry" and args.action == "validate":
        validate_registry_record(args.record, args.schema)
        print_json({"status": "passed", "record": str(args.record)})
    elif args.domain == "registry" and args.action == "rebuild-index":
        registry = FileRegistry(args.registry_root)
        label_index = registry.rebuild_label_index()
        print_json(
            {
                "status": "rebuilt",
                "label_index_items": len(label_index.get("items", {})),
            }
        )
    elif args.domain == "snapshot" and args.action == "create":
        print_json(create_snapshot(args.request, args.registry))
    elif args.domain == "snapshot" and args.action == "validate":
        snapshot = validate_snapshot(args.snapshot)
        print_json({"status": "passed", "snapshot_id": snapshot["snapshot_id"]})
    else:
        raise AssertionError("unhandled command")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run(args)
    except (SegPlatformError, ValueError, FileNotFoundError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
