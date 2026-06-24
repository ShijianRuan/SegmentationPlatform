from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from segplatform.common import canonical_id, load_data, utc_now, write_json
from segplatform.errors import ValidationError
from segplatform.registry import FileRegistry


WORKLIST_STATUSES = {"ready", "in_progress", "needs_review"}


def _copytree_replace(source: Path, destination: Path, *, overwrite: bool) -> None:
    if destination.exists():
        if not overwrite:
            raise ValidationError(f"destination already exists: {destination}")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _rebase_path(value: str, source_root: Path, destination_root: Path) -> str:
    path = Path(str(value))
    try:
        relative = path.resolve().relative_to(source_root.resolve())
    except (OSError, ValueError):
        return value
    return str((destination_root / relative).resolve())


def _rebase_artifact_paths(record: dict[str, Any], source_root: Path, destination_root: Path) -> dict[str, Any]:
    rebased = dict(record)
    if rebased.get("path"):
        rebased["path"] = _rebase_path(str(rebased["path"]), source_root, destination_root)
    if rebased.get("companion_paths"):
        rebased["companion_paths"] = [
            _rebase_path(str(path), source_root, destination_root) for path in rebased["companion_paths"]
        ]
    if rebased.get("segments"):
        rebased["segments"] = []
        for segment in record["segments"]:
            segment_copy = dict(segment)
            if segment_copy.get("path"):
                segment_copy["path"] = _rebase_path(str(segment_copy["path"]), source_root, destination_root)
            rebased["segments"].append(segment_copy)
    return rebased


def export_assignee_worklist(
    registry_root: Path,
    output_root: Path,
    *,
    assignee: str,
    local_cases_root: Path | None = None,
    include_statuses: set[str] | None = None,
    overwrite: bool = False,
    merge: bool = False,
    limit: int | None = None,
    claim_unassigned: bool = False,
) -> dict[str, Any]:
    """Copy assigned case packages and a minimal local Registry for a workstation."""

    registry = FileRegistry(registry_root)
    statuses = include_statuses or WORKLIST_STATUSES
    canonical_id(assignee, "assignee")
    output_root = output_root.resolve()
    cases_output_root = output_root / "cases"
    local_cases_base = (local_cases_root or cases_output_root).resolve()
    local_registry_root = output_root / "registry"

    if output_root.exists() and any(output_root.iterdir()) and not merge:
        if not overwrite:
            raise ValidationError(f"output root is not empty: {output_root}")
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    selected_reviews = []
    for review in registry.list("reviews"):
        if review.get("status") not in statuses or not review.get("package_path"):
            continue
        review_assignee = review.get("assignee")
        if review_assignee == assignee or (claim_unassigned and review_assignee in (None, "")):
            selected_reviews.append(review)
    selected_reviews.sort(key=lambda item: (item.get("created_at", ""), item["review_id"]))
    if limit is not None:
        selected_reviews = selected_reviews[: int(limit)]

    local_registry = FileRegistry(local_registry_root)
    exported_reviews = []
    copied_case_ids = set()
    copied_case_paths = set()
    copied_image_ids = set()
    copied_label_ids = set()

    for review in selected_reviews:
        if claim_unassigned and review.get("assignee") in (None, ""):
            review["assignee"] = assignee
            review.setdefault("events", []).append(
                {
                    "at": utc_now(),
                    "action": "claimed_for_worklist",
                    "actor": assignee,
                    "detail": str(output_root),
                }
            )
            registry.put("reviews", review, allow_update=True)
        case_id = review["case_id"]
        source_case_root = Path(str(review["package_path"])).resolve()
        if not source_case_root.is_dir():
            raise ValidationError(f"review package_path does not exist: {source_case_root}")
        destination_case_root = cases_output_root / source_case_root.name
        local_case_root = local_cases_base / source_case_root.name
        if str(source_case_root) not in copied_case_paths:
            if not destination_case_root.exists():
                _copytree_replace(source_case_root, destination_case_root, overwrite=overwrite)
            elif overwrite:
                _copytree_replace(source_case_root, destination_case_root, overwrite=True)
            copied_case_paths.add(str(source_case_root))
        if case_id not in copied_case_ids:
            local_case_record_path = local_registry.root / "cases" / f"{case_id}.json"
            if not local_case_record_path.exists():
                local_registry.put("cases", registry.get("cases", case_id))
            copied_case_ids.add(case_id)
        for image_id in registry.get("cases", case_id).get("image_ids", []):
            if image_id not in copied_image_ids:
                image_record = _rebase_artifact_paths(registry.get("images", image_id), source_case_root, local_case_root)
                local_image_record_path = local_registry.root / "images" / f"{image_id}.json"
                if not local_image_record_path.exists():
                    local_registry.put("images", image_record)
                copied_image_ids.add(image_id)
        for target in review.get("targets", []):
            label_id = target.get("base_label_id")
            if label_id and label_id not in copied_label_ids:
                label_record = _rebase_artifact_paths(registry.get("labels", label_id), source_case_root, local_case_root)
                local_label_record_path = local_registry.root / "labels" / f"{label_id}.json"
                if not local_label_record_path.exists():
                    local_registry.put("labels", label_record)
                copied_label_ids.add(label_id)

        local_review = dict(review)
        local_review["package_path"] = str((local_cases_base / case_id).resolve())
        local_review["package_path"] = str(local_case_root.resolve())
        local_review_record_path = local_registry.root / "reviews" / f"{review['review_id']}.json"
        if local_review_record_path.exists():
            if overwrite:
                local_registry.put("reviews", local_review, allow_update=True)
            else:
                continue
        else:
            local_registry.put("reviews", local_review)
        exported_reviews.append(
            {
                "review_id": review["review_id"],
                "case_id": case_id,
                "source_package_path": str(source_case_root),
                "local_package_path": local_review["package_path"],
            }
        )

    manifest = {
        "schema_version": "worklist_distribution.v1",
        "created_at": utc_now(),
        "assignee": assignee,
        "source_registry": str(registry_root.resolve()),
        "local_registry": str(local_registry_root.resolve()),
        "cases_root": str(cases_output_root.resolve()),
        "local_cases_root": str(local_cases_base),
        "review_count": len(exported_reviews),
        "reviews": exported_reviews,
    }
    write_json(output_root / "worklist_manifest.json", manifest)
    return {"status": "exported", **manifest}


def collect_submissions(
    returned_root: Path,
    central_cases_root: Path,
    *,
    registry_root: Path,
    overwrite: bool = False,
    include_working: bool = False,
) -> dict[str, Any]:
    """Collect Mimics submissions from returned workstation case packages."""

    registry = FileRegistry(registry_root)
    returned_root = returned_root.resolve()
    central_cases_root = central_cases_root.resolve()
    returned_cases = (
        sorted(path.parent for path in returned_root.rglob("manifest.json"))
        if not (returned_root / "manifest.json").is_file()
        else [returned_root]
    )
    results = []
    for returned_case_root in returned_cases:
        manifest = load_data(returned_case_root / "manifest.json")
        case_id = manifest["case_id"]
        review_id = manifest["review"]["review_id"]
        review_record = registry.get("reviews", review_id)
        central_case_root = Path(str(review_record.get("package_path") or "")).resolve()
        if not (central_case_root / "manifest.json").is_file():
            central_case_root = central_cases_root / case_id
        if not (central_case_root / "manifest.json").is_file():
            raise ValidationError(f"central case package does not exist: {central_case_root}")

        copied = []
        source_submission = returned_case_root / "submissions" / review_id
        if not (source_submission / "submission_manifest.json").is_file():
            results.append({"case_id": case_id, "review_id": review_id, "status": "skipped", "reason": "no_submission"})
            continue
        destination_submission = central_case_root / "submissions" / review_id
        _copytree_replace(source_submission, destination_submission, overwrite=overwrite)
        copied.append(str(destination_submission))

        source_reports = returned_case_root / "reports"
        if source_reports.is_dir():
            destination_reports = central_case_root / "reports"
            destination_reports.mkdir(exist_ok=True)
            for report in source_reports.iterdir():
                if not report.is_file():
                    continue
                destination = destination_reports / report.name
                if destination.exists() and not overwrite:
                    continue
                shutil.copy2(report, destination)
            copied.append(str(destination_reports))

        if include_working and (returned_case_root / "working").is_dir():
            destination_working = central_case_root / "working"
            _copytree_replace(returned_case_root / "working", destination_working, overwrite=overwrite)
            copied.append(str(destination_working))

        results.append({"case_id": case_id, "review_id": review_id, "status": "collected", "copied": copied})

    return {
        "status": "collected",
        "returned_root": str(returned_root),
        "central_cases_root": str(central_cases_root),
        "results": results,
    }
