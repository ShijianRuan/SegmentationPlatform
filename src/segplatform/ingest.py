from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import pydicom

from segplatform.common import load_data, utc_now, write_json, write_yaml
from segplatform.errors import ValidationError
from segplatform.imaging import inspect_dicom_files
from segplatform.vocabulary import AnatomyVocabulary


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def scan_source(source_root: Path) -> dict[str, Any]:
    """Discover importable DICOM series without creating registry records."""

    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ValidationError(f"ingest scan requires a directory: {source_root}")

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    for path in sorted(item for item in source_root.rglob("*") if item.is_file()):
        try:
            dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=False)
        except Exception:
            skipped.append({"path": _relative(path, source_root), "reason": "not_readable_as_dicom"})
            continue
        if not hasattr(dataset, "Rows") or not hasattr(dataset, "Columns"):
            skipped.append({"path": _relative(path, source_root), "reason": "dicom_without_pixel_matrix"})
            continue
        patient_key = str(dataset.get("PatientID", "")).strip()
        study_uid = str(dataset.get("StudyInstanceUID", "")).strip()
        series_uid = str(dataset.get("SeriesInstanceUID", "")).strip()
        if not study_uid or not series_uid:
            skipped.append({"path": _relative(path, source_root), "reason": "missing_study_or_series_uid"})
            continue
        key = (patient_key, study_uid, series_uid)
        group = groups.setdefault(
            key,
            {
                "patient_key_present": bool(patient_key),
                "study_uid": study_uid,
                "series_uid": series_uid,
                "files": [],
                "modalities": set(),
                "series_descriptions": set(),
            },
        )
        group["files"].append(path)
        modality = str(dataset.get("Modality", "")).strip()
        if modality:
            group["modalities"].add(modality)
        description = str(dataset.get("SeriesDescription", "")).strip()
        if description:
            group["series_descriptions"].add(description)

    series_records = []
    case_groups: dict[str, dict[str, Any]] = {}
    for (patient_key, study_uid, series_uid), group in sorted(groups.items(), key=lambda item: item[0]):
        case_seed = (patient_key or "unknown_patient") + "|" + study_uid
        case_id = "case_" + _short_hash(case_seed)
        study_id = "study_" + _short_hash(study_uid)
        if patient_key:
            leakage_group_id = "subject_" + _short_hash(patient_key)
            leakage_group_basis = "source_subject"
            leakage_group_confidence = "medium"
        else:
            leakage_group_id = study_id
            leakage_group_basis = "study"
            leakage_group_confidence = "low"
        image_id = "img_" + _short_hash(series_uid)
        relative_files = [_relative(path, source_root) for path in sorted(group["files"])]
        record: dict[str, Any] = {
            "case_id": case_id,
            "study_id": study_id,
            "image_id": image_id,
            "format": "dicom_series",
            "modality": sorted(group["modalities"])[0] if group["modalities"] else "UNKNOWN",
            "series_uid_sha256": _hash_text(series_uid),
            "study_instance_uid_sha256": _hash_text(study_uid),
            "series_descriptions": sorted(group["series_descriptions"]),
            "source_root": str(source_root),
            "source_files": relative_files,
            "file_count": len(relative_files),
            "leakage_group_id": leakage_group_id,
            "leakage_group_basis": leakage_group_basis,
            "leakage_group_confidence": leakage_group_confidence,
        }
        try:
            geometry, details = inspect_dicom_files(sorted(group["files"]), root=source_root)
            record.update(
                {
                    "status": "importable",
                    "sha256": details["hash"],
                    "hash_scope": details["hash_scope"],
                    "shape": list(geometry.shape),
                    "spacing": list(geometry.spacing),
                    "origin": list(geometry.origin),
                    "direction": list(geometry.direction),
                    "coordinate_system": geometry.coordinate_system,
                    "pixel_type": geometry.pixel_type,
                    "deidentification_scan": details["deidentification_scan"],
                }
            )
        except Exception as error:
            record.update({"status": "blocked", "reason": str(error)})
        series_records.append(record)
        case_group = case_groups.setdefault(
            case_id,
            {
                "case_id": case_id,
                "study_id": study_id,
                "leakage_group_id": leakage_group_id,
                "leakage_group_basis": leakage_group_basis,
                "leakage_group_confidence": leakage_group_confidence,
                "image_ids": [],
            },
        )
        case_group["image_ids"].append(image_id)

    cases = []
    for case in sorted(case_groups.values(), key=lambda item: item["case_id"]):
        case["image_ids"] = sorted(case["image_ids"])
        cases.append(case)
    return {
        "schema_version": "ingest_scan.v1",
        "created_at": utc_now(),
        "source_root": str(source_root),
        "reader": {"name": "pydicom", "version": pydicom.__version__},
        "cases": cases,
        "series": series_records,
        "skipped_files": skipped,
        "summary": {
            "case_count": len(cases),
            "series_count": len(series_records),
            "importable_series_count": sum(1 for item in series_records if item["status"] == "importable"),
            "skipped_file_count": len(skipped),
        },
    }


def build_case_package_requests(
    scan_path: Path,
    output_dir: Path,
    *,
    organs: list[str],
    import_batch: str,
    assignee: str | None = None,
    tool: str = "mimics",
    source_type: str = "dicom_scan",
    deidentification_status: str = "verified",
    governance_profile: str = "import_scan_profile",
    governance_profile_version: str = "1",
) -> dict[str, Any]:
    scan = load_data(scan_path)
    if scan.get("schema_version") != "ingest_scan.v1":
        raise ValidationError("scan file schema_version must be ingest_scan.v1")
    vocabulary = AnatomyVocabulary()
    normalized_organs = vocabulary.require_all(organs)
    output_dir = output_dir.expanduser().resolve()
    series_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for series in scan.get("series", []):
        if series.get("status") == "importable":
            series_by_case[str(series["case_id"])].append(series)

    written = []
    for case in scan.get("cases", []):
        case_id = str(case["case_id"])
        series_items = sorted(series_by_case.get(case_id, []), key=lambda item: item["image_id"])
        if not series_items:
            continue
        request = {
            "schema_version": "case_package_request.v1",
            "package_id": "pkg_" + case_id,
            "case_id": case_id,
            "study_id": str(case["study_id"]),
            "leakage_group_id": str(case["leakage_group_id"]),
            "leakage_group_basis": str(case["leakage_group_basis"]),
            "leakage_group_confidence": str(case["leakage_group_confidence"]),
            "data_governance": {
                "source_zone": "working",
                "deidentification_status": deidentification_status,
                "profile": governance_profile,
                "profile_version": governance_profile_version,
                "direct_identifiers_allowed": False,
            },
            "image_sets": [
                {
                    "image_id": series["image_id"],
                    "modality": series["modality"],
                    "format": "dicom_series",
                    "source": series["source_root"],
                    "source_files": series["source_files"],
                    "source_type": source_type,
                    "import_batch": import_batch,
                    "source_layout": {
                        "study": series["study_instance_uid_sha256"],
                        "series": series["series_uid_sha256"],
                    },
                    "allowed_dicom_tags": [],
                }
                for series in series_items
            ],
            "review": {
                "review_id": "review_" + case_id + "_v1",
                "tool": tool,
                "assignee": assignee,
                "targets": [
                    {
                        "target_id": "target_" + series["image_id"],
                        "image_id": series["image_id"],
                        "organs": normalized_organs,
                    }
                    for series in series_items
                ],
            },
            "initial_labels": [],
        }
        path = output_dir / f"{case_id}.yaml"
        write_yaml(path, request)
        written.append(str(path))
    summary = {
        "schema_version": "case_package_request_batch.v1",
        "created_at": utc_now(),
        "scan_path": str(scan_path),
        "request_count": len(written),
        "requests": written,
    }
    write_json(output_dir / "request_batch_summary.json", summary)
    return summary
