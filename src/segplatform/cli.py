from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from segplatform.adapters.mimics.doctor import doctor
from segplatform.adapters.mimics.finalize import finalize_case
from segplatform.adapters.mimics.launcher import open_case, prebuild_workspace
from segplatform.adapters.mimics.prepare import prepare_case
from segplatform.adapters.mimics.probes import evaluate_probe, run_probe
from segplatform.case_packages import create_case_package, validate_case_package, validate_registry_record
from segplatform.common import load_data
from segplatform.dataset_descriptions import build_requests_from_dataset_description
from segplatform.distribution import collect_submissions, export_assignee_worklist
from segplatform.errors import SegPlatformError
from segplatform.ingest import build_case_package_requests, register_scan, scan_source
from segplatform.labels import merge_labels, register_label, register_labels_from_table
from segplatform.registry import FileRegistry
from segplatform.review_updates import create_followup_reviews, create_followup_reviews_from_findings
from segplatform.reviews import defer_review, mark_review_started, next_review, reactivate_review, review_stats
from segplatform.runs import write_run_record
from segplatform.snapshots import build_snapshot_request, create_snapshot, validate_snapshot


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _split_values(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(item.strip() for item in value.split(",") if item.strip())
    return result


def _parse_label_map(values: list[str] | None) -> dict[str, int] | None:
    if not values:
        return None
    result: dict[str, int] = {}
    for raw in values:
        for item in raw.split(","):
            text = item.strip()
            if not text:
                continue
            if "=" not in text:
                raise SegPlatformError(f"label map item must use organ=value: {text}")
            organ, value = text.split("=", 1)
            result[organ.strip()] = int(value.strip())
    return result


def _parse_key_value(values: list[str] | None, *, name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values or []:
        for item in raw.split(","):
            text = item.strip()
            if not text:
                continue
            if "=" not in text:
                raise SegPlatformError(f"{name} item must use key=value: {text}")
            key, value = text.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def _request_files(root: Path) -> list[Path]:
    return sorted(
        path
        for pattern in ("*.yaml", "*.yml", "*.json")
        for path in root.glob(pattern)
        if path.name != "request_batch_summary.json"
    )


def _case_roots(root: Path) -> list[Path]:
    root = root.resolve()
    if (root / "manifest.json").is_file():
        return [root]
    return sorted(path.parent for path in root.rglob("manifest.json"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sp", description="SegmentationPlatform offline workflow")
    subparsers = parser.add_subparsers(dest="domain", required=True)

    ingest = subparsers.add_parser("ingest", help="Discover source data and generate package requests")
    ingest_sub = ingest.add_subparsers(dest="action", required=True)
    ingest_scan = ingest_sub.add_parser("scan")
    ingest_scan.add_argument("source_root", type=Path)
    ingest_scan.add_argument("--output", type=Path, required=True)
    ingest_register = ingest_sub.add_parser("register")
    ingest_register.add_argument("scan", type=Path)
    ingest_register.add_argument("--registry", type=Path, required=True)
    ingest_register.add_argument("--import-batch", required=True)
    ingest_register.add_argument("--source-type", default="ingest_scan")
    ingest_register.add_argument("--source-name")
    ingest_register.add_argument("--source-zone", default="working", choices=["restricted_raw", "working"])
    ingest_register.add_argument("--deidentification-status", default="verified", choices=["pending", "verified", "failed"])
    ingest_register.add_argument("--governance-profile", default="import_scan_profile")
    ingest_register.add_argument("--governance-profile-version", default="1")
    ingest_register.add_argument("--usability", default="allowed", choices=["allowed", "allowed_with_assumptions", "blocked"])
    ingest_register.add_argument("--allow-existing", action="store_true")
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
    ingest_description = ingest_sub.add_parser("from-description")
    ingest_description.add_argument("description", type=Path)
    ingest_description.add_argument("output_dir", type=Path)

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
    mimics_prepare_many = mimics_sub.add_parser("prepare-many")
    mimics_prepare_many.add_argument("cases_root", type=Path)
    mimics_prepare_many.add_argument("--config", type=Path, required=True)
    mimics_prepare_many.add_argument("--rebuild-workspace", action="store_true")
    mimics_prepare_many.add_argument("--continue-on-error", action="store_true")
    mimics_prebuild = mimics_sub.add_parser("prebuild-workspace")
    mimics_prebuild.add_argument("case_root", type=Path)
    mimics_prebuild.add_argument("--config", type=Path, required=True)
    mimics_prebuild.add_argument("--rebuild-workspace", action="store_true")
    mimics_prebuild.add_argument("--dry-run", action="store_true")
    mimics_prebuild.add_argument("--no-wait", action="store_true")
    mimics_prebuild_many = mimics_sub.add_parser("prebuild-many")
    mimics_prebuild_many.add_argument("cases_root", type=Path)
    mimics_prebuild_many.add_argument("--config", type=Path, required=True)
    mimics_prebuild_many.add_argument("--rebuild-workspace", action="store_true")
    mimics_prebuild_many.add_argument("--dry-run", action="store_true")
    mimics_prebuild_many.add_argument("--continue-on-error", action="store_true")
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
    mimics_finalize_many = mimics_sub.add_parser("finalize-many")
    mimics_finalize_many.add_argument("cases_root", type=Path)
    mimics_finalize_many.add_argument("--config", type=Path, required=True)
    mimics_finalize_many.add_argument("--registry", type=Path, required=True)
    mimics_finalize_many.add_argument("--continue-on-error", action="store_true")
    mimics_collect = mimics_sub.add_parser("collect-submissions")
    mimics_collect.add_argument("returned_root", type=Path)
    mimics_collect.add_argument("central_cases_root", type=Path)
    mimics_collect.add_argument("--registry", type=Path, required=True)
    mimics_collect.add_argument("--overwrite", action="store_true")
    mimics_collect.add_argument("--include-working", action="store_true")
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
    review_stats_parser = review_sub.add_parser("stats")
    review_stats_parser.add_argument("--registry", type=Path, required=True)
    review_next = review_sub.add_parser("next")
    review_next.add_argument("--registry", type=Path, required=True)
    review_next.add_argument("--assignee")
    review_next.add_argument("--include-status", action="append")
    review_next.add_argument("--exclude-review-id")
    review_start = review_sub.add_parser("start")
    review_start.add_argument("--registry", type=Path, required=True)
    review_start.add_argument("--review-id", required=True)
    review_start.add_argument("--actor")
    review_defer = review_sub.add_parser("defer")
    review_defer.add_argument("--registry", type=Path, required=True)
    review_defer.add_argument("--review-id", required=True)
    review_defer.add_argument("--actor")
    review_defer.add_argument("--reason")
    review_reactivate = review_sub.add_parser("reactivate")
    review_reactivate.add_argument("--registry", type=Path, required=True)
    review_reactivate.add_argument("--review-id", required=True)
    review_reactivate.add_argument("--actor")
    review_followup = review_sub.add_parser("create-followup")
    review_followup.add_argument("--registry", type=Path, required=True)
    review_followup.add_argument("--output-root", type=Path, required=True)
    review_followup.add_argument("--organs", nargs="+", required=True)
    review_followup.add_argument("--assignee")
    review_followup.add_argument("--case-id", action="append")
    review_followup.add_argument("--source-cases-root", type=Path)
    review_followup.add_argument("--review-suffix", default="followup")
    review_followup.add_argument("--allow-no-base", action="store_true")
    review_followup.add_argument("--overwrite", action="store_true")
    review_from_finding = review_sub.add_parser("create-from-finding")
    review_from_finding.add_argument("finding", type=Path)
    review_from_finding.add_argument("--registry", type=Path, required=True)
    review_from_finding.add_argument("--output-root", type=Path, required=True)
    review_from_finding.add_argument("--assignee")
    review_from_finding.add_argument("--source-cases-root", type=Path)
    review_from_finding.add_argument("--review-suffix", default="finding")
    review_from_finding.add_argument("--allow-no-base", action="store_true")
    review_from_finding.add_argument("--overwrite", action="store_true")
    review_export = review_sub.add_parser("export-worklist")
    review_export.add_argument("--registry", type=Path, required=True)
    review_export.add_argument("--assignee", required=True)
    review_export.add_argument("--output-root", type=Path, required=True)
    review_export.add_argument("--local-cases-root", type=Path)
    review_export.add_argument("--include-status", action="append")
    review_export.add_argument("--limit", type=int)
    review_export.add_argument("--merge", action="store_true")
    review_export.add_argument("--overwrite", action="store_true")

    label = subparsers.add_parser("label", help="Register and merge Label Artifacts")
    label_sub = label.add_subparsers(dest="action", required=True)
    label_register = label_sub.add_parser("register")
    label_register.add_argument("--registry", type=Path, required=True)
    label_register.add_argument("--case-id", required=True)
    label_register.add_argument("--image-id", required=True)
    label_register.add_argument("--mask", type=Path, required=True)
    label_register.add_argument("--organ")
    label_register.add_argument("--label-map", action="append")
    label_register.add_argument(
        "--lifecycle-status",
        default="source_label",
        choices=["source_label", "candidate_label", "draft_label", "verified_label", "rejected_label"],
    )
    label_register.add_argument(
        "--source-type",
        default="imported_dataset",
        choices=["imported_dataset", "manual_review", "model", "external_algorithm", "rule_script"],
    )
    label_register.add_argument("--source-name")
    label_register.add_argument("--generator-id")
    label_register.add_argument("--label-id")
    label_register.add_argument("--model-training", default="needs_policy")
    label_register.add_argument("--commercial-use", default="needs_policy")
    label_register.add_argument("--redistribution", default="needs_policy")
    label_register_many = label_sub.add_parser("register-many")
    label_register_many.add_argument("table", type=Path)
    label_register_many.add_argument("--registry", type=Path, required=True)
    label_register_many.add_argument(
        "--lifecycle-status",
        default="source_label",
        choices=["source_label", "candidate_label", "draft_label", "verified_label", "rejected_label"],
    )
    label_register_many.add_argument(
        "--source-type",
        default="imported_dataset",
        choices=["imported_dataset", "manual_review", "model", "external_algorithm", "rule_script"],
    )
    label_register_many.add_argument("--source-name")
    label_register_many.add_argument("--model-training", default="needs_policy")
    label_register_many.add_argument("--commercial-use", default="needs_policy")
    label_register_many.add_argument("--redistribution", default="needs_policy")
    label_register_many.add_argument("--continue-on-error", action="store_true")
    label_merge = label_sub.add_parser("merge")
    label_merge.add_argument("--registry", type=Path, required=True)
    label_merge.add_argument("--label-id", action="append", required=True)
    label_merge.add_argument("--output-label-id")
    label_merge.add_argument("--organ-source", action="append")
    label_merge.add_argument(
        "--lifecycle-status",
        choices=["source_label", "candidate_label", "draft_label", "verified_label", "rejected_label"],
    )
    label_merge.add_argument("--supersede-inputs", action="store_true")

    registry = subparsers.add_parser("registry", help="Validate registry records")
    registry_sub = registry.add_subparsers(dest="action", required=True)
    registry_validate = registry_sub.add_parser("validate")
    registry_validate.add_argument("record", type=Path)
    registry_validate.add_argument("--schema", required=True)
    registry_rebuild = registry_sub.add_parser("rebuild-index")
    registry_rebuild.add_argument("registry_root", type=Path)

    snapshot = subparsers.add_parser("snapshot", help="Create the immutable pre-training dataset snapshot")
    snapshot_sub = snapshot.add_subparsers(dest="action", required=True)
    snapshot_build = snapshot_sub.add_parser("build-request")
    snapshot_build.add_argument("--registry", type=Path, required=True)
    snapshot_build.add_argument("--output", type=Path, required=True)
    snapshot_build.add_argument("--snapshot-id", required=True)
    snapshot_build.add_argument("--task-id", required=True)
    snapshot_build.add_argument("--organs", nargs="+", required=True)
    snapshot_build.add_argument("--split-plan", type=Path)
    snapshot_build.add_argument("--default-split", choices=["train", "val", "test"], default="train")
    snapshot_build.add_argument("--allow-lifecycle-status", action="append")
    snapshot_build.add_argument("--require-all-organs", action="store_true")
    snapshot_build.add_argument("--preprocess-name", default="none")
    snapshot_build.add_argument("--created-by", default="offline_operator")
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
    elif args.domain == "ingest" and args.action == "register":
        print_json(
            register_scan(
                args.scan,
                args.registry,
                import_batch=args.import_batch,
                source_type=args.source_type,
                source_name=args.source_name,
                source_zone=args.source_zone,
                deidentification_status=args.deidentification_status,
                governance_profile=args.governance_profile,
                governance_profile_version=args.governance_profile_version,
                usability=args.usability,
                allow_existing=args.allow_existing,
            )
        )
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
    elif args.domain == "ingest" and args.action == "from-description":
        print_json(build_requests_from_dataset_description(args.description, args.output_dir))
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
    elif args.domain == "mimics" and args.action == "prepare-many":
        results = []
        had_error = False
        for case_root in _case_roots(args.cases_root):
            try:
                runtime_path = prepare_case(case_root, args.config, rebuild_workspace=args.rebuild_workspace)
                results.append(
                    {"case_root": str(case_root), "status": "prepared", "runtime_manifest": str(runtime_path)}
                )
            except Exception as error:
                had_error = True
                results.append({"case_root": str(case_root), "status": "failed", "error": str(error)})
                if not args.continue_on_error:
                    break
        print_json({"status": "failed" if had_error else "prepared", "results": results})
        if had_error:
            return 2
    elif args.domain == "mimics" and args.action == "prebuild-workspace":
        result = prebuild_workspace(
            args.case_root,
            args.config,
            rebuild_workspace=args.rebuild_workspace,
            dry_run=args.dry_run,
            wait=not args.no_wait,
        )
        print_json(result)
        if result.get("returncode") not in (None, 0):
            return 2
    elif args.domain == "mimics" and args.action == "prebuild-many":
        results = []
        had_error = False
        for case_root in _case_roots(args.cases_root):
            try:
                result = prebuild_workspace(
                    case_root,
                    args.config,
                    rebuild_workspace=args.rebuild_workspace,
                    dry_run=args.dry_run,
                    wait=True,
                )
                results.append({"case_root": str(case_root), **result})
                if result.get("returncode") not in (None, 0):
                    had_error = True
                    if not args.continue_on_error:
                        break
            except Exception as error:
                had_error = True
                results.append({"case_root": str(case_root), "status": "failed", "error": str(error)})
                if not args.continue_on_error:
                    break
        print_json({"status": "failed" if had_error else "prebuilt", "results": results})
        if had_error:
            return 2
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
    elif args.domain == "mimics" and args.action == "finalize-many":
        results = []
        had_error = False
        for case_root in _case_roots(args.cases_root):
            try:
                manifest = load_data(case_root / "manifest.json")
                review_id = manifest["review"]["review_id"]
                submission = case_root / "submissions" / review_id / "submission_manifest.json"
                if not submission.is_file():
                    results.append({"case_root": str(case_root), "status": "skipped", "reason": "no_submission"})
                    continue
                result = finalize_case(case_root, args.config, args.registry)
                results.append({"case_root": str(case_root), **result})
            except Exception as error:
                had_error = True
                results.append({"case_root": str(case_root), "status": "failed", "error": str(error)})
                if not args.continue_on_error:
                    break
        print_json({"status": "failed" if had_error else "finalized", "results": results})
        if had_error:
            return 2
    elif args.domain == "mimics" and args.action == "collect-submissions":
        print_json(
            collect_submissions(
                args.returned_root,
                args.central_cases_root,
                registry_root=args.registry,
                overwrite=args.overwrite,
                include_working=args.include_working,
            )
        )
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
    elif args.domain == "review" and args.action == "stats":
        print_json(review_stats(args.registry))
    elif args.domain == "review" and args.action == "next":
        statuses = set(args.include_status or []) or None
        print_json(
            next_review(
                args.registry,
                assignee=args.assignee,
                include_statuses=statuses,
                exclude_review_id=args.exclude_review_id,
            )
        )
    elif args.domain == "review" and args.action == "start":
        print_json(mark_review_started(args.registry, args.review_id, actor=args.actor))
    elif args.domain == "review" and args.action == "defer":
        print_json(defer_review(args.registry, args.review_id, actor=args.actor, reason=args.reason))
    elif args.domain == "review" and args.action == "reactivate":
        print_json(reactivate_review(args.registry, args.review_id, actor=args.actor))
    elif args.domain == "review" and args.action == "create-followup":
        print_json(
            create_followup_reviews(
                args.registry,
                args.output_root,
                organs=_split_values(args.organs),
                assignee=args.assignee,
                case_ids=args.case_id,
                source_cases_root=args.source_cases_root,
                review_suffix=args.review_suffix,
                allow_no_base=args.allow_no_base,
                overwrite=args.overwrite,
            )
        )
    elif args.domain == "review" and args.action == "create-from-finding":
        result = create_followup_reviews_from_findings(
            args.registry,
            args.output_root,
            args.finding,
            assignee=args.assignee,
            source_cases_root=args.source_cases_root,
            review_suffix=args.review_suffix,
            allow_no_base=args.allow_no_base,
            overwrite=args.overwrite,
        )
        run = write_run_record(
            args.registry,
            action="review.create-from-finding",
            status=result["status"],
            inputs={"finding": str(args.finding), "output_root": str(args.output_root)},
            outputs={"review_count": result.get("review_count", 0)},
            result={"unsupported_count": len(result.get("unsupported", []))},
        )
        print_json({**result, "run_id": run["run_id"], "run_record_path": run["run_record_path"]})
    elif args.domain == "review" and args.action == "export-worklist":
        statuses = set(args.include_status or []) or None
        print_json(
            export_assignee_worklist(
                args.registry,
                args.output_root,
                assignee=args.assignee,
                local_cases_root=args.local_cases_root,
                include_statuses=statuses,
                overwrite=args.overwrite,
                merge=args.merge,
                limit=args.limit,
            )
        )
    elif args.domain == "label" and args.action == "register":
        print_json(
            register_label(
                args.registry,
                case_id=args.case_id,
                image_id=args.image_id,
                mask_path=args.mask,
                organ=args.organ,
                label_map=_parse_label_map(args.label_map),
                lifecycle_status=args.lifecycle_status,
                source_type=args.source_type,
                source_name=args.source_name,
                generator_id=args.generator_id,
                label_id=args.label_id,
                model_training=args.model_training,
                commercial_use=args.commercial_use,
                redistribution=args.redistribution,
            )
        )
    elif args.domain == "label" and args.action == "register-many":
        result = register_labels_from_table(
            args.registry,
            args.table,
            lifecycle_status=args.lifecycle_status,
            source_type=args.source_type,
            source_name=args.source_name,
            model_training=args.model_training,
            commercial_use=args.commercial_use,
            redistribution=args.redistribution,
            continue_on_error=args.continue_on_error,
        )
        run = write_run_record(
            args.registry,
            action="label.register-many",
            status=result["status"],
            inputs={"table": str(args.table)},
            outputs={"registered_count": result.get("registered_count", 0)},
            result={"failed_count": result.get("failed_count", 0)},
        )
        print_json({**result, "run_id": run["run_id"], "run_record_path": run["run_record_path"]})
        if result["status"] == "failed":
            return 2
    elif args.domain == "label" and args.action == "merge":
        result = merge_labels(
            args.registry,
            label_ids=args.label_id,
            label_id=args.output_label_id,
            organ_sources=_parse_key_value(args.organ_source, name="organ-source"),
            lifecycle_status=args.lifecycle_status,
            supersede_inputs=args.supersede_inputs,
        )
        run = write_run_record(
            args.registry,
            action="label.merge",
            status=result["status"],
            inputs={"label_ids": args.label_id},
            outputs={"label_id": result["label_id"]},
            result={"superseded_label_ids": result.get("superseded_label_ids", [])},
        )
        print_json({**result, "run_id": run["run_id"], "run_record_path": run["run_record_path"]})
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
    elif args.domain == "snapshot" and args.action == "build-request":
        print_json(
            build_snapshot_request(
                args.registry,
                args.output,
                snapshot_id=args.snapshot_id,
                task_id=args.task_id,
                organs=_split_values(args.organs),
                split_plan=args.split_plan,
                default_split=args.default_split,
                allow_lifecycle_status=_split_values(args.allow_lifecycle_status or []) or None,
                require_all_organs=args.require_all_organs,
                preprocess_name=args.preprocess_name,
                created_by=args.created_by,
            )
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
