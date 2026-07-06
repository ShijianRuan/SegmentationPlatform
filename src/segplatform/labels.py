from __future__ import annotations

import csv
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from segplatform.common import canonical_id, hash_directory
from segplatform.errors import ValidationError
from segplatform.imaging import geometry_from_manifest, geometry_matches, read_mask, write_mask_nifti
from segplatform.registry import FileRegistry
from segplatform.schema import validate_schema
from segplatform.vocabulary import AnatomyVocabulary


LIFECYCLE_STATUSES = {"source_label", "candidate_label", "draft_label", "verified_label", "rejected_label"}
SEGMENT_SOURCE_TYPES = {"imported_dataset", "manual_review", "model", "external_algorithm", "rule_script"}
CONSTRAINT_VALUES = {"allowed", "allowed_with_policy", "needs_policy", "needs_review", "forbidden"}
CONSTRAINT_RANK = {
    "allowed": 0,
    "allowed_with_policy": 1,
    "needs_policy": 2,
    "needs_review": 3,
    "forbidden": 4,
}


def _usage_constraints(
    *,
    model_training: str,
    commercial_use: str,
    redistribution: str,
) -> dict[str, str]:
    values = {
        "model_training": model_training,
        "commercial_use": commercial_use,
        "redistribution": redistribution,
    }
    invalid = {key: value for key, value in values.items() if value not in CONSTRAINT_VALUES}
    if invalid:
        raise ValidationError(f"invalid usage constraint values: {invalid}")
    return values


def _most_restrictive_usage(records: list[dict[str, Any]]) -> dict[str, str]:
    keys = {"model_training", "commercial_use", "redistribution"}
    for record in records:
        keys.update(record.get("usage_constraints", {}).keys())
    merged = {}
    for key in sorted(keys):
        values = [
            str(record.get("usage_constraints", {}).get(key, "needs_policy"))
            for record in records
        ]
        invalid = [value for value in values if value not in CONSTRAINT_RANK]
        if invalid:
            raise ValidationError(f"invalid usage constraint values in input labels: {invalid}")
        merged[key] = max(values, key=lambda value: CONSTRAINT_RANK[value])
    return merged


def _label_mappings(
    *,
    organ: str | None,
    label_map: dict[str, int] | None,
    vocabulary: AnatomyVocabulary,
) -> dict[str, int]:
    if organ and label_map:
        raise ValidationError("use either organ or label_map, not both")
    if organ:
        return {vocabulary.normalize(organ): 1}
    if not label_map:
        raise ValidationError("label registration requires organ or label_map")
    result = {}
    for key, value in label_map.items():
        normalized = vocabulary.normalize(str(key))
        if normalized in result:
            raise ValidationError(f"duplicate organ after alias normalization: {key} -> {normalized}")
        result[normalized] = int(value)
    if 0 in result.values():
        raise ValidationError("label_map values must be foreground integers; 0 is reserved for background")
    values = list(result.values())
    if len(values) != len(set(values)):
        raise ValidationError(f"label_map values must be unique: {label_map}")
    return result


def _validate_mask_values(array: np.ndarray, mappings: dict[str, int], mask_path: Path) -> None:
    values = set(int(value) for value in np.unique(array))
    if set(mappings.values()) == {1} and len(mappings) == 1:
        if not values.issubset({0, 1}):
            raise ValidationError(f"single-organ mask must contain only 0/1: {mask_path}")
        return
    unknown = values - {0, *mappings.values()}
    if unknown:
        raise ValidationError(f"multilabel mask contains unknown values {sorted(unknown)}: {mask_path}")


def _parse_label_map_value(value: Any) -> dict[str, int] | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        return {str(key): int(raw) for key, raw in value.items()}
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValidationError("label_map must parse to a JSON object")
        return {str(key): int(raw) for key, raw in parsed.items()}
    result: dict[str, int] = {}
    for item in text.split(","):
        entry = item.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValidationError(f"label_map item must use organ=value: {entry}")
        organ, raw_value = entry.split("=", 1)
        result[organ.strip()] = int(raw_value.strip())
    return result or None


def _load_registration_rows(path: Path) -> list[dict[str, Any]]:
    suffixes = "".join(path.suffixes).lower()
    if suffixes.endswith(".csv"):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    text = path.read_text(encoding="utf-8")
    if suffixes.endswith(".json"):
        payload = json.loads(text)
    else:
        from segplatform.common import load_data

        payload = load_data(path)
    if isinstance(payload, list):
        return [dict(row) for row in payload]
    if isinstance(payload, dict):
        rows = payload.get("labels") or payload.get("registrations") or payload.get("rows")
        if isinstance(rows, list):
            return [dict(row) for row in rows]
    raise ValidationError("label registration table must be CSV, a list, or an object with labels/registrations/rows")


def _label_record_geometry_key(record: dict[str, Any]) -> tuple[Any, ...]:
    geometry = record.get("geometry", {})
    return (
        tuple(geometry.get("shape", [])),
        tuple(round(float(value), 8) for value in geometry.get("spacing", [])),
        tuple(round(float(value), 8) for value in geometry.get("origin", [])),
        tuple(round(float(value), 8) for value in geometry.get("direction", [])),
        geometry.get("geometry_status"),
        geometry.get("alignment_basis"),
    )


def _selected_segments(
    records: list[dict[str, Any]],
    organ_sources: dict[str, str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_organ: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for record in records:
        for segment in record.get("segments", []):
            by_organ.setdefault(segment["organ"], []).append((record, segment))
    selected = []
    for organ, candidates in sorted(by_organ.items()):
        if len(candidates) == 1:
            selected.append(candidates[0])
            continue
        selected_label_id = organ_sources.get(organ)
        if not selected_label_id:
            raise ValidationError(
                f"organ {organ} appears in multiple labels; specify --organ-source {organ}=label_id"
            )
        matches = [candidate for candidate in candidates if candidate[0]["label_id"] == selected_label_id]
        if len(matches) != 1:
            raise ValidationError(f"organ-source {organ}={selected_label_id} does not match input labels")
        selected.append(matches[0])
    unknown_organs = sorted(set(organ_sources) - set(by_organ))
    if unknown_organs:
        raise ValidationError(f"organ-source references organs not present in input labels: {unknown_organs}")
    return selected


def register_label(
    registry_root: Path,
    *,
    case_id: str,
    image_id: str,
    mask_path: Path,
    organ: str | None = None,
    label_map: dict[str, int] | None = None,
    lifecycle_status: str = "source_label",
    source_type: str = "imported_dataset",
    source_name: str | None = None,
    generator_id: str | None = None,
    label_id: str | None = None,
    model_training: str = "needs_policy",
    commercial_use: str = "needs_policy",
    redistribution: str = "needs_policy",
) -> dict[str, Any]:
    """Register an external mask as a Label Artifact for an existing Image Artifact."""

    registry = FileRegistry(registry_root)
    case_id = canonical_id(case_id, "case_id")
    image_id = canonical_id(image_id, "image_id")
    if lifecycle_status not in LIFECYCLE_STATUSES:
        raise ValidationError(f"invalid lifecycle_status: {lifecycle_status}")
    if source_type not in SEGMENT_SOURCE_TYPES:
        raise ValidationError(f"invalid source_type: {source_type}")
    case_record = registry.get("cases", case_id)
    if image_id not in case_record["image_ids"]:
        raise ValidationError(f"case {case_id} does not reference image {image_id}")
    image_record = registry.get("images", image_id)
    if image_record["case_id"] != case_id:
        raise ValidationError(f"image {image_id} belongs to another case")

    vocabulary = AnatomyVocabulary()
    mappings = _label_mappings(organ=organ, label_map=label_map, vocabulary=vocabulary)
    source_mask = mask_path.expanduser().resolve()
    array, label_geometry = read_mask(source_mask)
    image_geometry = geometry_from_manifest(
        {
            **image_record,
            "coordinate_system": image_record.get("geometry_evidence", {}).get("coordinate_system", "unknown"),
        }
    )
    matches, reasons = geometry_matches(image_geometry, label_geometry)
    if not matches:
        raise ValidationError(f"label geometry does not match image {image_id}: " + "; ".join(reasons))
    _validate_mask_values(array, mappings, source_mask)

    artifact_root = registry.root / "_artifacts" / "labels"
    temporary_root = artifact_root / (".partial_" + uuid.uuid4().hex)
    masks_root = temporary_root / "masks"
    try:
        for mapped_organ, value in mappings.items():
            write_mask_nifti(masks_root / f"{mapped_organ}.nii.gz", array == value, image_geometry)
        bundle_hash = hash_directory(temporary_root)
        selected_label_id = canonical_id(
            label_id or f"label_{image_id}_registered_{bundle_hash[7:19]}",
            "label_id",
        )
        if (registry.root / "labels" / f"{selected_label_id}.json").exists():
            raise ValidationError(f"registry label already exists: {selected_label_id}")
        destination_root = artifact_root / selected_label_id
        if destination_root.exists():
            raise ValidationError(f"registered label artifact path already exists: {destination_root}")
        destination_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_root), str(destination_root))
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)

    segment_source: dict[str, Any] = {"type": source_type}
    if source_name:
        segment_source["name"] = source_name
    if generator_id:
        segment_source["generator_id"] = generator_id
    contributing = [generator_id] if generator_id and source_type in {"model", "external_algorithm", "rule_script"} else []
    segments = [
        {
            "organ": mapped_organ,
            "path": str((destination_root / "masks" / f"{mapped_organ}.nii.gz").resolve()),
            "lifecycle_status": lifecycle_status,
            "source": dict(segment_source),
            "lineage": {
                "derived_from_label_ids": [],
                "contributing_generators": contributing,
            },
        }
        for mapped_organ in sorted(mappings)
    ]
    label_record = {
        "schema_version": "label_artifact.v1",
        "label_id": selected_label_id,
        "case_id": case_id,
        "image_id": image_id,
        "path": str(destination_root.resolve()),
        "format": "per_organ_masks",
        "hash": hash_directory(destination_root),
        "hash_scope": "bundle_manifest",
        "pixel_type": "uint8",
        "geometry_ref": image_id,
        "geometry": {
            "shape": list(image_geometry.shape),
            "spacing": list(image_geometry.spacing),
            "origin": list(image_geometry.origin),
            "direction": list(image_geometry.direction),
            "geometry_status": "complete",
            "geometry_evidence": {
                "shape": "sidecar",
                "spacing": "sidecar",
                "origin": "sidecar",
                "direction": "sidecar",
                "assumptions": [],
            },
            "alignment_checked": True,
            "alignment_basis": "physical_space",
        },
        "artifact_lifecycle": "active",
        "usage_constraints": _usage_constraints(
            model_training=model_training,
            commercial_use=commercial_use,
            redistribution=redistribution,
        ),
        "parent_label_id": None,
        "segments": segments,
    }
    validate_schema(label_record, "label_artifact.schema.json")
    registry.put("labels", label_record)
    return {"status": "registered", "label_id": selected_label_id, "record": label_record}


def register_labels_from_table(
    registry_root: Path,
    table_path: Path,
    *,
    lifecycle_status: str = "source_label",
    source_type: str = "imported_dataset",
    source_name: str | None = None,
    model_training: str = "needs_policy",
    commercial_use: str = "needs_policy",
    redistribution: str = "needs_policy",
    continue_on_error: bool = False,
) -> dict[str, Any]:
    """Register many external masks from a CSV/JSON/YAML table."""

    rows = _load_registration_rows(table_path)
    results = []
    had_error = False
    for index, row in enumerate(rows, start=1):
        try:
            mask = row.get("mask") or row.get("mask_path") or row.get("path")
            if not mask:
                raise ValidationError("row requires mask/mask_path/path")
            result = register_label(
                registry_root,
                case_id=str(row["case_id"]),
                image_id=str(row["image_id"]),
                mask_path=Path(str(mask)),
                organ=str(row["organ"]) if row.get("organ") else None,
                label_map=_parse_label_map_value(row.get("label_map")),
                lifecycle_status=str(row.get("lifecycle_status") or lifecycle_status),
                source_type=str(row.get("source_type") or source_type),
                source_name=str(row.get("source_name") or source_name) if (row.get("source_name") or source_name) else None,
                generator_id=str(row.get("generator_id")) if row.get("generator_id") else None,
                label_id=str(row.get("label_id")) if row.get("label_id") else None,
                model_training=str(row.get("model_training") or model_training),
                commercial_use=str(row.get("commercial_use") or commercial_use),
                redistribution=str(row.get("redistribution") or redistribution),
            )
            results.append({"row": index, "status": "registered", "label_id": result["label_id"]})
        except Exception as error:
            had_error = True
            results.append({"row": index, "status": "failed", "error": str(error)})
            if not continue_on_error:
                break
    return {
        "status": "failed" if had_error else "registered",
        "registered_count": len([item for item in results if item["status"] == "registered"]),
        "failed_count": len([item for item in results if item["status"] == "failed"]),
        "results": results,
    }


def merge_labels(
    registry_root: Path,
    *,
    label_ids: list[str],
    label_id: str | None = None,
    organ_sources: dict[str, str] | None = None,
    lifecycle_status: str | None = None,
    supersede_inputs: bool = False,
) -> dict[str, Any]:
    """Merge non-conflicting segments from multiple Label Artifacts into one active artifact."""

    if len(label_ids) < 2:
        raise ValidationError("label merge requires at least two input labels")
    registry = FileRegistry(registry_root)
    input_records = [registry.get("labels", canonical_id(raw, "label_id")) for raw in label_ids]
    case_ids = {record["case_id"] for record in input_records}
    image_ids = {record["image_id"] for record in input_records}
    if len(case_ids) != 1 or len(image_ids) != 1:
        raise ValidationError("label merge inputs must belong to the same case_id and image_id")
    inactive = [record["label_id"] for record in input_records if record.get("artifact_lifecycle") != "active"]
    if inactive:
        raise ValidationError(f"label merge inputs must be active: {inactive}")
    geometry_keys = {_label_record_geometry_key(record) for record in input_records}
    if len(geometry_keys) != 1:
        raise ValidationError("label merge inputs have incompatible geometry metadata")

    vocabulary = AnatomyVocabulary()
    normalized_sources = {
        vocabulary.normalize(organ): canonical_id(source, "label_id")
        for organ, source in (organ_sources or {}).items()
    }
    selected = _selected_segments(input_records, normalized_sources)
    case_id = next(iter(case_ids))
    image_id = next(iter(image_ids))
    destination_label_id = canonical_id(label_id or f"label_{image_id}_merged_{uuid.uuid4().hex[:12]}", "label_id")
    destination_root = registry.root / "_artifacts" / "labels" / destination_label_id
    if (registry.root / "labels" / f"{destination_label_id}.json").exists():
        raise ValidationError(f"registry label already exists: {destination_label_id}")
    if destination_root.exists():
        raise ValidationError(f"merged label artifact path already exists: {destination_root}")
    temporary_root = registry.root / "_artifacts" / "labels" / (".partial_" + uuid.uuid4().hex)
    masks_root = temporary_root / "masks"
    segments = []
    try:
        for source_record, source_segment in selected:
            organ = source_segment["organ"]
            source_path = Path(str(source_segment["path"]))
            if not source_path.is_file():
                raise ValidationError(f"source segment mask does not exist: {source_path}")
            destination = masks_root / f"{organ}.nii.gz"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
            lineage = source_segment.get("lineage", {})
            derived = sorted(set(lineage.get("derived_from_label_ids", [])) | {source_record["label_id"]})
            segments.append(
                {
                    "organ": organ,
                    "path": str(destination.resolve()),
                    "lifecycle_status": lifecycle_status or source_segment["lifecycle_status"],
                    "source": {"type": "rule_script", "name": "sp label merge"},
                    "lineage": {
                        "derived_from_label_ids": derived,
                        "contributing_generators": sorted(set(lineage.get("contributing_generators", []))),
                    },
                }
            )
        destination_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_root), str(destination_root))
    finally:
        if temporary_root.exists():
            shutil.rmtree(temporary_root)

    first = input_records[0]
    for segment in segments:
        segment["path"] = str((destination_root / "masks" / f"{segment['organ']}.nii.gz").resolve())
    label_record = {
        "schema_version": "label_artifact.v1",
        "label_id": destination_label_id,
        "case_id": case_id,
        "image_id": image_id,
        "path": str(destination_root.resolve()),
        "format": "per_organ_masks",
        "hash": hash_directory(destination_root),
        "hash_scope": "bundle_manifest",
        "pixel_type": first.get("pixel_type", "uint8"),
        "geometry_ref": image_id,
        "geometry": dict(first["geometry"]),
        "artifact_lifecycle": "active",
        "usage_constraints": _most_restrictive_usage(input_records),
        "parent_label_id": None,
        "segments": sorted(segments, key=lambda item: item["organ"]),
    }
    validate_schema(label_record, "label_artifact.schema.json")
    registry.put("labels", label_record)
    superseded = []
    if supersede_inputs:
        for record in input_records:
            record["artifact_lifecycle"] = "superseded"
            registry.put("labels", record, allow_update=True)
            superseded.append(record["label_id"])
    return {
        "status": "merged",
        "label_id": destination_label_id,
        "input_label_ids": [record["label_id"] for record in input_records],
        "superseded_label_ids": superseded,
        "record": label_record,
    }
