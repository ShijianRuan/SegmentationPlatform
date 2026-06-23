from __future__ import annotations

from pathlib import Path
from typing import Any
import csv

from segplatform.common import load_data, utc_now, write_yaml
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

USABILITY_VALUES = {"allowed", "allowed_with_assumptions", "blocked"}


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


def _snapshot_usability_purpose(split: str) -> str:
    return "training" if split == "train" else "evaluation"


def _image_record_for_snapshot(
    registry: FileRegistry,
    case_record: dict[str, Any],
    image_id: str,
) -> dict[str, Any]:
    image_record = registry.get("images", image_id)
    if image_record.get("case_id") != case_record["case_id"]:
        raise ValidationError(f"image {image_id} belongs to another case")
    return image_record


def _image_usability_for_split(image_record: dict[str, Any], split: str) -> tuple[str, str]:
    purpose = _snapshot_usability_purpose(split)
    usability = image_record.get("usability")
    if not isinstance(usability, dict):
        raise ValidationError(f"image {image_record['image_id']} is missing usability metadata")
    value = usability.get(purpose)
    if value not in USABILITY_VALUES:
        raise ValidationError(f"image {image_record['image_id']} has invalid usability.{purpose}: {value!r}")
    return purpose, value


def _format_blocked_image_message(image_record: dict[str, Any], purpose: str) -> str:
    reasons = image_record.get("usability", {}).get("reasons", [])
    suffix = "" if not reasons else ": " + "; ".join(str(reason) for reason in reasons)
    return f"image {image_record['image_id']} usability.{purpose} is blocked{suffix}"


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
        image_record = _image_record_for_snapshot(registry, case_record, image_id)
        usability_purpose, usability_value = _image_usability_for_split(image_record, split)
        if usability_value == "blocked":
            raise ValidationError(_format_blocked_image_message(image_record, usability_purpose))
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
                "image_hash": image_record["hash"],
                "image_usability": {
                    "purpose": usability_purpose,
                    "value": usability_value,
                    "reasons": image_record["usability"].get("reasons", []),
                },
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


def _load_split_plan(path: Path | None) -> dict[tuple[str, str | None], str]:
    if path is None:
        return {}
    result: dict[tuple[str, str | None], str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"case_id", "split"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValidationError("split plan CSV must contain at least case_id and split columns")
        for row in reader:
            case_id = str(row["case_id"]).strip()
            image_id = str(row.get("image_id") or "").strip() or None
            split = str(row["split"]).strip()
            if split not in {"train", "val", "test"}:
                raise ValidationError(f"invalid split in split plan: {split}")
            result[(case_id, image_id)] = split
    return result


def build_snapshot_request(
    registry_root: Path,
    output_path: Path,
    *,
    snapshot_id: str,
    task_id: str,
    organs: list[str],
    split_plan: Path | None = None,
    default_split: str = "train",
    allow_lifecycle_status: list[str] | None = None,
    require_all_organs: bool = False,
    preprocess_name: str = "none",
    created_by: str = "offline_operator",
) -> dict[str, Any]:
    """Generate a snapshot_request.v1 draft from active Registry labels."""

    if default_split not in {"train", "val", "test"}:
        raise ValidationError(f"default_split must be train, val or test: {default_split}")
    registry = FileRegistry(registry_root)
    vocabulary = AnatomyVocabulary()
    normalized_organs = vocabulary.require_all(organs)
    allowed_statuses = allow_lifecycle_status or ["verified_label"]
    splits = _load_split_plan(split_plan)
    label_map = {"background": 0}
    for index, organ in enumerate(normalized_organs, start=1):
        label_map[organ] = index

    cases = []
    skipped = []
    for case_record in registry.list("cases"):
        case_id = case_record["case_id"]
        for image_id in case_record["image_ids"]:
            split = splits.get((case_id, image_id)) or splits.get((case_id, None)) or default_split
            try:
                image_record = _image_record_for_snapshot(registry, case_record, image_id)
                usability_purpose, usability_value = _image_usability_for_split(image_record, split)
            except ValidationError as error:
                skipped.append(
                    {
                        "case_id": case_id,
                        "image_id": image_id,
                        "reason": "image_usability_invalid",
                        "message": str(error),
                    }
                )
                continue
            if usability_value == "blocked":
                skipped.append(
                    {
                        "case_id": case_id,
                        "image_id": image_id,
                        "reason": "image_usability_blocked",
                        "usability_purpose": usability_purpose,
                        "usability_value": usability_value,
                        "reasons": image_record["usability"].get("reasons", []),
                    }
                )
                continue
            segments = []
            missing = []
            ambiguous = []
            rejected_status = []
            for organ in normalized_organs:
                candidates = registry.find_labels(case_id=case_id, image_id=image_id, organ=organ)
                accepted = []
                for candidate in candidates:
                    for segment in candidate.get("segments", []):
                        if segment.get("organ") == organ:
                            if segment.get("lifecycle_status") in allowed_statuses:
                                accepted.append(candidate)
                            else:
                                rejected_status.append(
                                    {
                                        "organ": organ,
                                        "label_id": candidate["label_id"],
                                        "lifecycle_status": segment.get("lifecycle_status"),
                                    }
                                )
                            break
                if len(accepted) == 1:
                    segments.append({"organ": organ, "label_id": accepted[0]["label_id"]})
                elif len(accepted) > 1:
                    ambiguous.append({"organ": organ, "label_ids": [item["label_id"] for item in accepted]})
                else:
                    missing.append(organ)
            if ambiguous:
                skipped.append(
                    {
                        "case_id": case_id,
                        "image_id": image_id,
                        "reason": "ambiguous_labels",
                        "ambiguous": ambiguous,
                    }
                )
                continue
            if require_all_organs and missing:
                skipped.append(
                    {
                        "case_id": case_id,
                        "image_id": image_id,
                        "reason": "missing_required_organs",
                        "missing_organs": missing,
                    }
                )
                continue
            if not segments:
                skipped.append(
                    {
                        "case_id": case_id,
                        "image_id": image_id,
                        "reason": "no_allowed_labels",
                        "missing_organs": missing,
                        "rejected_status": rejected_status,
                    }
                )
                continue
            cases.append(
                {
                    "case_id": case_id,
                    "image_id": image_id,
                    "split": split,
                    "segments": segments,
                }
            )

    request = {
        "schema_version": "snapshot_request.v1",
        "snapshot_id": snapshot_id,
        "task_id": task_id,
        "created_by": created_by,
        "task_label_map": label_map,
        "label_policy": {"allow_lifecycle_status": allowed_statuses},
        "cases": cases,
        "preprocess_profile": {"name": preprocess_name},
        "usage_constraints": {
            "model_training": "needs_policy",
            "commercial_use": "needs_policy",
            "redistribution": "needs_policy",
        },
    }
    write_yaml(output_path, request)
    report = {
        "status": "built",
        "output": str(output_path.resolve()),
        "case_image_count": len(cases),
        "skipped_count": len(skipped),
        "skipped": skipped,
    }
    return report
