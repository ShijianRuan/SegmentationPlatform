from __future__ import annotations

import copy
import shutil
import uuid
from pathlib import Path
from typing import Any

from segplatform.common import canonical_id, load_data, utc_now, write_json
from segplatform.errors import ValidationError
from segplatform.registry import FileRegistry
from segplatform.schema import validate_schema


WORKLIST_STATUSES = {"ready", "in_progress", "needs_review"}
WORKLIST_ENTRY_SCRIPTS = (
    "Labeling_Open_Next_Case.py",
    "Labeling_Case_Navigation.py",
    "Labeling_Submit_Complete.py",
    "Labeling_Submit_or_Report_Issue.py",
    "Labeling_View_Task_List.py",
    "Labeling_Save_Recovery_Backup.py",
)

NNINTERACTIVE_ENTRY_SCRIPTS = ("nnInteractive.py",)
NNINTERACTIVE_RUNTIME_SCRIPTS = ("nninteractive_mimics.py",)
NNINTERACTIVE_ROOT_FILES = ("nninteractive_bridge.py",)


def _copytree_replace(source: Path, destination: Path, *, overwrite: bool) -> None:
    if destination.exists():
        if not overwrite:
            raise ValidationError(f"destination already exists: {destination}")
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _copy_worklist_runtime(output_root: Path) -> list[str]:
    repository_root = Path(__file__).resolve().parents[2]
    mimics_root = repository_root / "adapters" / "mimics"
    scripting_library = mimics_root / "scripting_library"
    source_runtime = mimics_root / "runtime_py35"
    if not scripting_library.is_dir() or not source_runtime.is_dir():
        raise ValidationError("Mimics worklist runtime files are missing from the repository")

    for name in WORKLIST_ENTRY_SCRIPTS:
        source = scripting_library / name
        if not source.is_file():
            raise ValidationError(f"Mimics worklist entry is missing: {source}")
        shutil.copy2(source, output_root / name)
    runtime_output = output_root / "runtime_py35"
    runtime_output.mkdir(parents=True, exist_ok=True)
    required_runtime = (
        "sp_common.py",
        "sp_open_review.py",
        "sp_review_console.py",
        "sp_save_checkpoint.py",
        "sp_submit_review.py",
    )
    for name in required_runtime:
        source = source_runtime / name
        if not source.is_file():
            raise ValidationError(f"Mimics worklist runtime file is missing: {source}")
        shutil.copy2(source, runtime_output / name)

    # Optionally include nnInteractive scripts when they exist in the repo.
    # The external Python env + model must still be installed separately.
    nninteractive_available = all(
        (scripting_library / name).is_file() for name in NNINTERACTIVE_ENTRY_SCRIPTS
    ) and all(
        (source_runtime / name).is_file() for name in NNINTERACTIVE_RUNTIME_SCRIPTS
    ) and (mimics_root / "nninteractive_bridge.py").is_file()

    if nninteractive_available:
        for name in NNINTERACTIVE_ENTRY_SCRIPTS:
            shutil.copy2(scripting_library / name, output_root / name)
        for name in NNINTERACTIVE_RUNTIME_SCRIPTS:
            shutil.copy2(source_runtime / name, runtime_output / name)
        for name in NNINTERACTIVE_ROOT_FILES:
            shutil.copy2(mimics_root / name, output_root / name)
    return list(WORKLIST_ENTRY_SCRIPTS) + (
        list(NNINTERACTIVE_ENTRY_SCRIPTS) if nninteractive_available else []
    )


def _validate_prepared_review(
    review: dict[str, Any],
    source_case_root: Path,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = source_case_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValidationError(f"case package manifest is missing: {manifest_path}")
    manifest = load_data(manifest_path)
    expected = {
        "review_id": str(review["review_id"]),
        "package_id": str(review["package_id"]),
        "case_id": str(review["case_id"]),
    }
    manifest_review_id = str((manifest.get("review") or {}).get("review_id") or "")
    actual = {
        "review_id": str(runtime.get("review_id") or ""),
        "package_id": str(runtime.get("package_id") or ""),
        "case_id": str(runtime.get("case_id") or ""),
    }
    mismatches = [
        f"runtime.{key}={actual[key]!r}, expected {value!r}"
        for key, value in expected.items()
        if actual[key] != value
    ]
    if str(manifest.get("package_id") or "") != expected["package_id"]:
        mismatches.append(
            f"manifest.package_id={manifest.get('package_id')!r}, expected {expected['package_id']!r}"
        )
    if str(manifest.get("case_id") or "") != expected["case_id"]:
        mismatches.append(
            f"manifest.case_id={manifest.get('case_id')!r}, expected {expected['case_id']!r}"
        )
    if manifest_review_id != expected["review_id"]:
        mismatches.append(
            f"manifest.review.review_id={manifest_review_id!r}, expected {expected['review_id']!r}"
        )
    if mismatches:
        raise ValidationError(
            f"review {review['review_id']} package/runtime identity mismatch: "
            + "; ".join(mismatches)
        )
    return manifest


def export_worklist(
    registry_root: Path,
    output_root: Path,
    *,
    assignee: str | None = None,
    include_statuses: set[str] | None = None,
    overwrite: bool = False,
    merge: bool = False,
    limit: int | None = None,
    claim_unassigned: bool = False,
    include_distributed: bool = False,
) -> dict[str, Any]:
    """Create a movable Mimics worklist that has no local Registry dependency."""

    registry = FileRegistry(registry_root)
    statuses = include_statuses or WORKLIST_STATUSES
    if claim_unassigned and not assignee:
        raise ValidationError("--claim-unassigned requires --assignee")
    if limit is not None and int(limit) <= 0:
        raise ValidationError("--limit must be greater than zero")
    if assignee:
        canonical_id(assignee, "assignee")
    output_root = output_root.resolve()
    cases_output_root = output_root / "cases"

    output_has_contents = output_root.exists() and any(output_root.iterdir())
    if output_has_contents and not merge and not overwrite:
        raise ValidationError(f"output root is not empty: {output_root}")
    existing_manifest = None
    existing_manifest_path = output_root / "worklist_manifest.json"
    if merge and existing_manifest_path.is_file():
        existing_manifest = load_data(existing_manifest_path)
        if existing_manifest.get("schema_version") != "mimics_worklist.v2":
            raise ValidationError("can only merge into a mimics_worklist.v2 worklist")
    elif merge and output_has_contents:
        raise ValidationError("cannot merge into a non-empty directory without worklist_manifest.json")
    worklist_id = (
        existing_manifest["worklist_id"]
        if existing_manifest
        else f"worklist_{uuid.uuid4().hex[:12]}"
    )
    existing_reviews = list(existing_manifest.get("reviews", [])) if existing_manifest else []
    existing_review_ids = {entry["review_id"] for entry in existing_reviews}

    selected_reviews = []
    for review in registry.list("reviews"):
        if review.get("status") not in statuses or not review.get("package_path"):
            continue
        if review["review_id"] in existing_review_ids:
            continue
        if review.get("worklist_exports") and not include_distributed:
            continue
        review_assignee = review.get("assignee")
        if assignee is None:
            selected_reviews.append(review)
        elif review_assignee == assignee or (claim_unassigned and review_assignee in (None, "")):
            selected_reviews.append(review)
    selected_reviews.sort(key=lambda item: (item.get("created_at", ""), item["review_id"]))
    if limit is not None:
        selected_reviews = selected_reviews[: int(limit)]

    if not selected_reviews and not existing_reviews:
        raise ValidationError("no reviews matched the requested worklist filters")

    prepared_sources: dict[str, tuple[Path, dict[str, Any], Path]] = {}
    for review in selected_reviews:
        if review.get("enforce_assignee", False):
            if not assignee:
                raise ValidationError(
                    f"review {review['review_id']} enforces assignee identity; export it with --assignee"
                )
            if review.get("assignee") not in (assignee, None, ""):
                raise ValidationError(
                    f"review {review['review_id']} is assigned to {review.get('assignee')}, not {assignee}"
                )
            if review.get("assignee") in (None, "") and not claim_unassigned:
                raise ValidationError(
                    f"review {review['review_id']} enforces assignee identity; use --claim-unassigned"
                )
        source_case_root = Path(str(review["package_path"])).resolve()
        if not source_case_root.is_dir():
            raise ValidationError(f"review package_path does not exist: {source_case_root}")
        source_runtime = source_case_root / "working" / "mimics_runtime.json"
        if not source_runtime.is_file():
            raise ValidationError(
                f"review {review['review_id']} is not prepared for offline Mimics use; "
                f"run 'sp mimics prepare' first"
            )
        runtime = load_data(source_runtime)
        _validate_prepared_review(review, source_case_root, runtime)
        source_mcs = Path(str(runtime.get("mcs_path") or source_case_root / "working" / f"{review['review_id']}.mcs"))
        try:
            source_mcs.resolve().relative_to(source_case_root)
        except ValueError as error:
            raise ValidationError(
                f"review {review['review_id']} mcs_path must stay inside its case package: {source_mcs}"
            ) from error
        prepared_sources[review["review_id"]] = (source_case_root, runtime, source_mcs)

    if output_has_contents and not merge and overwrite:
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    exported_reviews = []
    copied_case_paths = set()

    for review in selected_reviews:
        case_id = review["case_id"]
        source_case_root, _runtime, source_mcs = prepared_sources[review["review_id"]]
        destination_case_root = cases_output_root / source_case_root.name
        if str(source_case_root) not in copied_case_paths:
            if not destination_case_root.exists():
                _copytree_replace(source_case_root, destination_case_root, overwrite=overwrite)
            elif overwrite:
                _copytree_replace(source_case_root, destination_case_root, overwrite=True)
            copied_case_paths.add(str(source_case_root))
        exported_reviews.append(
            {
                "review_id": review["review_id"],
                "case_id": case_id,
                "package_path": f"cases/{source_case_root.name}",
                "runtime_path": f"cases/{source_case_root.name}/working/mimics_runtime.json",
                "mcs_path": str(
                    Path("cases") / source_case_root.name / source_mcs.resolve().relative_to(source_case_root)
                ).replace("\\", "/"),
                "workspace_mode": "prebuilt" if source_mcs.is_file() else "build_on_first_open",
                "status_at_export": review.get("status"),
                "recipient_hint": assignee,
                "submission_assignee": assignee if review.get("enforce_assignee", False) else None,
            }
        )

    exported_reviews = existing_reviews + [
        entry for entry in exported_reviews if entry["review_id"] not in existing_review_ids
    ]

    entry_scripts = _copy_worklist_runtime(output_root)
    manifest = {
        "schema_version": "mimics_worklist.v2",
        "worklist_id": worklist_id,
        "created_at": utc_now(),
        "recipient_hint": assignee,
        "paths_are_relative_to": "worklist_root",
        "cases_root": "cases",
        "state_path": "worklist_progress.json",
        "entry_scripts": entry_scripts,
        "review_count": len(exported_reviews),
        "reviews": exported_reviews,
    }
    state_path = output_root / "worklist_progress.json"
    if not state_path.is_file():
        write_json(
            state_path,
            {
                "schema_version": "mimics_worklist_progress.v1",
                "worklist_id": worklist_id,
                "current_review_id": None,
                "items": {},
            },
        )
    exported_at = utc_now()
    original_reviews = {
        review["review_id"]: copy.deepcopy(review)
        for review in selected_reviews
    }
    updated_reviews = []
    for review in selected_reviews:
        updated = copy.deepcopy(review)
        if assignee and claim_unassigned and updated.get("assignee") in (None, ""):
            updated["assignee"] = assignee
        updated.setdefault("worklist_exports", []).append(
            {
                "worklist_id": worklist_id,
                "exported_at": exported_at,
                "recipient_hint": assignee,
            }
        )
        updated.setdefault("events", []).append(
            {
                "at": exported_at,
                "action": "worklist_exported",
                "actor": assignee or "platform",
                "detail": worklist_id,
            }
        )
        validate_schema(updated, "review_task.schema.json")
        updated_reviews.append(updated)

    written_review_ids = []
    try:
        for updated in updated_reviews:
            registry.put("reviews", updated, allow_update=True)
            written_review_ids.append(updated["review_id"])
        # Publish the manifest last. Until this atomic write succeeds, copied
        # files are not a runnable worklist.
        write_json(output_root / "worklist_manifest.json", manifest)
    except Exception:
        for review_id in reversed(written_review_ids):
            registry.put("reviews", original_reviews[review_id], allow_update=True)
        raise
    return {"status": "exported", **manifest}


def export_assignee_worklist(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Backward-compatible alias for callers using the former assignee-centric name."""

    return export_worklist(*args, **kwargs)


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
