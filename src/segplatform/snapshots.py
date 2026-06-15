from __future__ import annotations

from pathlib import Path
from typing import Any

from segplatform.common import load_data, utc_now
from segplatform.errors import ValidationError
from segplatform.registry import FileRegistry
from segplatform.schema import validate_schema
from segplatform.vocabulary import AnatomyVocabulary


CONSTRAINT_ORDER = {
    "allowed": 0,
    "allowed_with_policy": 1,
    "needs_policy": 2,
    "needs_review": 3,
    "forbidden": 4,
}


def _merge_constraints(values: list[dict[str, str]]) -> dict[str, str]:
    keys = set()
    for value in values:
        keys.update(value)
    return {
        key: max((value.get(key, "needs_policy") for value in values), key=lambda item: CONSTRAINT_ORDER[item])
        for key in sorted(keys)
    }


def _validate_label_map(label_map: dict[str, Any], vocabulary: AnatomyVocabulary) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for organ, value in label_map.items():
        key = "background" if organ == "background" else vocabulary.normalize(str(organ))
        if key in normalized:
            raise ValidationError(f"duplicate task label after alias normalization: {organ} -> {key}")
        normalized[key] = int(value)
    if normalized.get("background") != 0:
        raise ValidationError("task_label_map.background must be 0")
    invalid_zero = [organ for organ, value in normalized.items() if organ != "background" and value == 0]
    if invalid_zero:
        raise ValidationError(f"only background may use label value 0: {invalid_zero}")
    values = sorted(set(normalized.values()))
    if values != list(range(max(values) + 1)):
        raise ValidationError(f"task label values must be continuous from 0; found {values}")
    return normalized


def _segment_from_label(record: dict[str, Any], organ: str) -> dict[str, Any]:
    segments = [segment for segment in record["segments"] if segment["organ"] == organ]
    if len(segments) != 1:
        raise ValidationError(f"label {record['label_id']} must contain exactly one segment for {organ}")
    return segments[0]


def create_snapshot(request_path: Path, registry_root: Path) -> dict[str, Any]:
    request = load_data(request_path)
    if request.get("schema_version") != "snapshot_request.v1":
        raise ValidationError("snapshot request schema_version must be snapshot_request.v1")
    registry = FileRegistry(registry_root)
    vocabulary = AnatomyVocabulary()
    label_map = _validate_label_map(dict(request["task_label_map"]), vocabulary)
    allowed_statuses = set(request["label_policy"]["allow_lifecycle_status"])
    if not request.get("cases"):
        raise ValidationError("snapshot request must contain at least one case")
    snapshot_cases = []
    split_by_leakage_group: dict[str, str] = {}
    selected_constraints = []
    seen_case_images: set[tuple[str, str]] = set()

    for requested_case in request["cases"]:
        case_record = registry.get("cases", str(requested_case["case_id"]))
        image_id = str(requested_case["image_id"])
        case_image_key = (case_record["case_id"], image_id)
        if case_image_key in seen_case_images:
            raise ValidationError(f"duplicate snapshot case/image entry: {case_image_key}")
        seen_case_images.add(case_image_key)
        if image_id not in case_record["image_ids"]:
            raise ValidationError(f"case {case_record['case_id']} does not reference image {image_id}")
        split = str(requested_case["split"])
        leakage_group = case_record["leakage_group_id"]
        previous_split = split_by_leakage_group.get(leakage_group)
        if previous_split and previous_split != split:
            raise ValidationError(
                f"leakage group {leakage_group} appears in both {previous_split} and {split}"
            )
        split_by_leakage_group[leakage_group] = split
        if (
            split in {"val", "test"}
            and case_record["leakage_group_confidence"] == "low"
            and not request.get("allow_low_confidence_evaluation", False)
        ):
            raise ValidationError(
                f"{case_record['case_id']}: low-confidence leakage group cannot be used for {split}"
            )
        if not requested_case.get("segments"):
            raise ValidationError(f"{case_record['case_id']}/{image_id}: snapshot segments cannot be empty")
        requested_segments = []
        seen_organs = set()
        for item in requested_case["segments"]:
            organ = vocabulary.normalize(str(item["organ"]))
            if organ in seen_organs:
                raise ValidationError(f"{case_record['case_id']}/{image_id}: duplicate segment {organ}")
            seen_organs.add(organ)
            if organ not in label_map:
                raise ValidationError(f"organ {organ} is not in task_label_map")
            label_id = item.get("label_id")
            if label_id:
                label_record = registry.get("labels", str(label_id))
            else:
                candidates = registry.find_labels(case_id=case_record["case_id"], image_id=image_id, organ=organ)
                if len(candidates) != 1:
                    raise ValidationError(
                        f"{case_record['case_id']}/{image_id}/{organ}: expected one active label, found {len(candidates)}; specify label_id"
                    )
                label_record = candidates[0]
            if label_record["case_id"] != case_record["case_id"] or label_record["image_id"] != image_id:
                raise ValidationError(f"label {label_record['label_id']} belongs to another case or image")
            segment = _segment_from_label(label_record, organ)
            selected_constraints.append(
                label_record.get(
                    "usage_constraints",
                    {
                        "model_training": "needs_policy",
                        "commercial_use": "needs_policy",
                        "redistribution": "needs_policy",
                    },
                )
            )
            lifecycle = segment["lifecycle_status"]
            admission = "accepted" if lifecycle in allowed_statuses else "rejected"
            if admission == "rejected":
                raise ValidationError(
                    f"label {label_record['label_id']} segment {organ} has lifecycle {lifecycle}, which policy rejects"
                )
            requested_segments.append(
                {
                    "organ": organ,
                    "label_id": label_record["label_id"],
                    "label_hash": label_record["hash"],
                    "lifecycle_status": lifecycle,
                    "admission_result": admission,
                }
            )
        snapshot_cases.append(
            {
                "case_id": case_record["case_id"],
                "image_id": image_id,
                "split": split,
                "leakage_group_id": leakage_group,
                "leakage_group_basis": case_record["leakage_group_basis"],
                "leakage_group_confidence": case_record["leakage_group_confidence"],
                "segments": requested_segments,
            }
        )

    snapshot = {
        "schema_version": "dataset_snapshot.v1",
        "snapshot_id": str(request["snapshot_id"]),
        "task_id": str(request["task_id"]),
        "created_by": str(request.get("created_by", "offline_operator")),
        "created_at": utc_now(),
        "task_label_map": label_map,
        "label_policy": request["label_policy"],
        "split": {
            "leakage_key": "leakage_group_id",
            **({"source_split_plan": request["source_split_plan"]} if request.get("source_split_plan") else {}),
        },
        "cases": snapshot_cases,
        "preprocess_profile": request.get("preprocess_profile", {"name": "none"}),
        "usage_constraints": _merge_constraints(
            selected_constraints
            + [
                request.get(
                    "usage_constraints",
                    {
                        "model_training": "needs_policy",
                        "commercial_use": "needs_policy",
                        "redistribution": "needs_policy",
                    },
                )
            ]
        ),
    }
    if snapshot["usage_constraints"].get("model_training") == "forbidden":
        raise ValidationError("selected data usage constraints forbid model training")
    validate_schema(snapshot, "dataset_snapshot.schema.json")
    registry.put("snapshots", snapshot)
    return snapshot


def validate_snapshot(path: Path) -> dict[str, Any]:
    snapshot = load_data(path)
    validate_schema(snapshot, "dataset_snapshot.schema.json")
    seen: dict[str, str] = {}
    for case in snapshot["cases"]:
        group = case["leakage_group_id"]
        split = case["split"]
        if group in seen and seen[group] != split:
            raise ValidationError(f"leakage group {group} crosses {seen[group]} and {split}")
        seen[group] = split
    return snapshot
