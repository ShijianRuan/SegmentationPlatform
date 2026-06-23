from __future__ import annotations

import hashlib
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pydicom

from segplatform.common import load_data, utc_now, write_json, write_yaml
from segplatform.errors import ValidationError
from segplatform.imaging import infer_format, inspect_dicom_files, inspect_image
from segplatform.registry import FileRegistry
from segplatform.vocabulary import AnatomyVocabulary


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _case_seed_for_file(relative_path: str) -> str:
    relative = Path(relative_path)
    if str(relative.parent) in ("", "."):
        return relative.as_posix()
    return relative.parent.as_posix()


def _file_image_record(path: Path, source_root: Path, format_name: str) -> dict[str, Any]:
    relative = _relative(path, source_root)
    case_seed = _case_seed_for_file(relative)
    case_id = "case_" + _short_hash(case_seed)
    study_id = "study_" + _short_hash(case_seed)
    image_id = "img_" + _short_hash(relative)
    record: dict[str, Any] = {
        "case_id": case_id,
        "study_id": study_id,
        "image_id": image_id,
        "format": format_name,
        "modality": "UNKNOWN",
        "source_root": str(source_root),
        "source_path": str(path),
        "source_relative_path": relative,
        "file_count": 1,
        "leakage_group_id": "source_path_" + _short_hash(case_seed),
        "leakage_group_basis": "source_path_group",
        "leakage_group_confidence": "low",
    }
    try:
        geometry, details = inspect_image(path, format_name)
        record.update(
            {
                "status": "importable",
                "sha256": details["hash"],
                "hash_scope": details["hash_scope"],
                "reader": details["reader"],
                "shape": list(geometry.shape),
                "spacing": list(geometry.spacing),
                "origin": list(geometry.origin),
                "direction": list(geometry.direction),
                "coordinate_system": geometry.coordinate_system,
                "pixel_type": geometry.pixel_type,
            }
        )
        if details.get("companion_paths"):
            record["companion_paths"] = details["companion_paths"]
    except Exception as error:
        record.update({"status": "blocked", "reason": str(error)})
    return record


def scan_source(source_root: Path) -> dict[str, Any]:
    """Discover importable image sets without creating registry records.

    DICOM is grouped by StudyInstanceUID and SeriesInstanceUID. File-based
    images are grouped by their parent directory as a conservative default.
    Complex dataset-specific layouts should still use an explicit package
    request or a future dataset-description importer.
    """

    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise ValidationError(f"ingest scan requires a directory: {source_root}")

    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    skipped: list[dict[str, Any]] = []
    file_image_records = []
    all_files = sorted(item for item in source_root.rglob("*") if item.is_file())
    total = len(all_files)
    last_log = 0.0
    log_interval = 2.0
    for idx, path in enumerate(all_files):
        now = time.time()
        if now - last_log >= log_interval:
            pct = (idx + 1) / total * 100 if total else 100
            print(
                f"[scan] {idx + 1}/{total} files ({pct:.0f}%)  "
                f"DICOM groups: {len(groups)}  skipped: {len(skipped)}",
                file=sys.stderr,
            )
            last_log = now
        format_name = infer_format(path)
        if format_name in {"nifti", "metaimage"}:
            file_image_records.append(_file_image_record(path, source_root, format_name))
            continue
        if format_name == "raw_binary":
            skipped.append({"path": _relative(path, source_root), "reason": "raw_binary_requires_sidecar"})
            continue
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
    total_series = len(groups)
    for series_idx, (patient_key, study_uid, series_uid) in enumerate(
        sorted(groups.keys(), key=lambda item: item[0])
    ):
        group = groups[(patient_key, study_uid, series_uid)]
        print(
            f"[scan] inspecting series {series_idx + 1}/{total_series}: "
            f"{group['modalities'] or '?'} - {series_uid[:12]}..."
            f"  ({len(group['files'])} files)",
            file=sys.stderr,
        )
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
                    "reader": details["reader"],
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

    for record in sorted(file_image_records, key=lambda item: item["image_id"]):
        series_records.append(record)
        case_group = case_groups.setdefault(
            record["case_id"],
            {
                "case_id": record["case_id"],
                "study_id": record["study_id"],
                "leakage_group_id": record["leakage_group_id"],
                "leakage_group_basis": record["leakage_group_basis"],
                "leakage_group_confidence": record["leakage_group_confidence"],
                "image_ids": [],
            },
        )
        case_group["image_ids"].append(record["image_id"])

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
            "file_image_count": len(file_image_records),
            "skipped_file_count": len(skipped),
        },
    }
    s = report["summary"]
    print(
        f"[scan] done: {s['case_count']} cases, {s['series_count']} DICOM series, "
        f"{s['file_image_count']} file-based images, {s['skipped_file_count']} skipped",
        file=sys.stderr,
    )
    return report


def _data_governance(
    *,
    source_zone: str,
    deidentification_status: str,
    governance_profile: str,
    governance_profile_version: str,
) -> dict[str, Any]:
    if source_zone == "working" and deidentification_status != "verified":
        raise ValidationError("source_zone=working requires deidentification_status=verified")
    return {
        "source_zone": source_zone,
        "deidentification_status": deidentification_status,
        "profile": governance_profile,
        "profile_version": governance_profile_version,
        "direct_identifiers_allowed": False,
    }


def _registry_leakage_basis(value: str) -> str:
    if value == "source_path_group":
        return "case"
    if value in {"patient_pseudonym", "source_subject", "study", "case", "import_batch_unknown"}:
        return value
    return "case"


def _scan_geometry_evidence(record: dict[str, Any]) -> dict[str, Any]:
    source = "dicom" if record.get("format") == "dicom_series" else "header"
    return {
        "coordinate_system": record.get("coordinate_system", "unknown"),
        "shape": source,
        "spacing": source,
        "origin": source,
        "direction": source,
        "assumptions": [],
    }


def _scan_source_layout(record: dict[str, Any]) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "study": record.get("study_instance_uid_sha256", record.get("study_id", "")),
        "series": record.get("series_uid_sha256", record.get("source_relative_path", record.get("image_id", ""))),
    }
    if record.get("source_relative_path"):
        layout["relative_path"] = record["source_relative_path"]
    if record.get("source_files"):
        layout["source_files"] = list(record["source_files"])
    return {key: value for key, value in layout.items() if value}


def _scan_image_artifact(
    scan: dict[str, Any],
    record: dict[str, Any],
    *,
    import_batch: str,
    source_type: str,
    source_name: str | None,
    usability: str,
) -> dict[str, Any]:
    if record.get("status") != "importable":
        raise ValidationError(f"image {record.get('image_id')} is not importable")
    image_path = record["source_root"] if record["format"] == "dicom_series" else record["source_path"]
    source = {
        "type": source_type,
        "import_batch": import_batch,
        "source_layout": _scan_source_layout(record),
        "reader": record.get("reader") or scan.get("reader") or {"name": "unknown", "version": "unknown"},
    }
    if source_name:
        source["name"] = source_name
    artifact = {
        "schema_version": "image_artifact.v1",
        "image_id": record["image_id"],
        "case_id": record["case_id"],
        "modality": record.get("modality", "UNKNOWN"),
        "format": record["format"],
        "path": str(image_path),
        "hash": record["sha256"],
        "hash_scope": record["hash_scope"],
        "pixel_type": record["pixel_type"],
        "shape": record["shape"],
        "spacing": record["spacing"],
        "origin": record["origin"],
        "direction": record["direction"],
        "geometry_status": record.get("geometry_status", "complete"),
        "geometry_evidence": record.get("geometry_evidence", _scan_geometry_evidence(record)),
        "source": source,
        "usability": {
            "annotation": usability,
            "training": usability,
            "evaluation": usability,
            "reasons": [],
        },
    }
    if record.get("companion_paths"):
        artifact["companion_paths"] = list(record["companion_paths"])
    return artifact


def register_scan(
    scan_path: Path,
    registry_root: Path,
    *,
    import_batch: str,
    source_type: str = "ingest_scan",
    source_name: str | None = None,
    source_zone: str = "working",
    deidentification_status: str = "verified",
    governance_profile: str = "import_scan_profile",
    governance_profile_version: str = "1",
    usability: str = "allowed",
    allow_existing: bool = False,
) -> dict[str, Any]:
    """Register scan-discovered Case and Image Artifacts without creating case packages."""

    scan = load_data(scan_path)
    if scan.get("schema_version") != "ingest_scan.v1":
        raise ValidationError("scan file schema_version must be ingest_scan.v1")
    if usability not in {"allowed", "allowed_with_assumptions", "blocked"}:
        raise ValidationError(f"invalid usability value: {usability}")

    governance = _data_governance(
        source_zone=source_zone,
        deidentification_status=deidentification_status,
        governance_profile=governance_profile,
        governance_profile_version=governance_profile_version,
    )
    registry = FileRegistry(registry_root)
    importable_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in scan.get("series", []):
        if record.get("status") == "importable":
            importable_by_case[str(record["case_id"])].append(record)

    registered_cases = 0
    registered_images = 0
    skipped: list[dict[str, Any]] = []
    for case in scan.get("cases", []):
        case_id = str(case["case_id"])
        records = sorted(importable_by_case.get(case_id, []), key=lambda item: item["image_id"])
        if not records:
            skipped.append({"case_id": case_id, "reason": "no_importable_images"})
            continue
        case_record = {
            "schema_version": "case_manifest.v1",
            "case_id": case_id,
            "leakage_group_id": str(case["leakage_group_id"]),
            "leakage_group_basis": _registry_leakage_basis(str(case.get("leakage_group_basis", "case"))),
            "leakage_group_confidence": str(case.get("leakage_group_confidence", "low")),
            "study_id": str(case["study_id"]),
            "image_ids": [str(record["image_id"]) for record in records],
            "data_governance": governance,
        }
        try:
            registry.put("cases", case_record)
            registered_cases += 1
        except ValidationError as error:
            if not allow_existing:
                raise
            skipped.append({"case_id": case_id, "reason": "case_exists", "message": str(error)})

        for record in records:
            artifact = _scan_image_artifact(
                scan,
                record,
                import_batch=import_batch,
                source_type=source_type,
                source_name=source_name,
                usability=usability,
            )
            try:
                registry.put("images", artifact)
                registered_images += 1
            except ValidationError as error:
                if not allow_existing:
                    raise
                skipped.append(
                    {
                        "case_id": case_id,
                        "image_id": artifact["image_id"],
                        "reason": "image_exists",
                        "message": str(error),
                    }
                )

    return {
        "status": "registered",
        "scan_path": str(scan_path.resolve()),
        "registry_root": str(registry_root.resolve()),
        "registered_cases": registered_cases,
        "registered_images": registered_images,
        "skipped": skipped,
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
        image_sets = []
        for series in series_items:
            image_set = {
                "image_id": series["image_id"],
                "modality": series["modality"],
                "format": series["format"],
                "source": series["source_root"] if series["format"] == "dicom_series" else series["source_path"],
                "source_type": source_type,
                "import_batch": import_batch,
                "source_layout": {
                    "study": series.get("study_instance_uid_sha256", series["study_id"]),
                    "series": series.get("series_uid_sha256", series.get("source_relative_path", series["image_id"])),
                },
                "allowed_dicom_tags": [],
            }
            if series["format"] == "dicom_series":
                image_set["source_files"] = series["source_files"]
            image_sets.append(image_set)

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
            "image_sets": image_sets,
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
