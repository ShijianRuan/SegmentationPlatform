from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from segplatform.adapters.mimics.bridge import BufferMappingSet, prepare_import_buffers, write_buffer_manifest
from segplatform.adapters.mimics.doctor import load_workstation_config
from segplatform.case_packages import validate_case_package
from segplatform.common import ensure_within, load_data, prefixed_sha256, utc_now, write_json
from segplatform.errors import ConfigurationError, ValidationError
from segplatform.imaging import voxel_count


def _runtime_mask_name(target_id: str, organ: str) -> str:
    return f"SP__{target_id}__{organ}"


def _load_checkpoint_buffers(
    case_root: Path,
    manifest: dict[str, Any],
    mapping_set: BufferMappingSet,
) -> list[dict[str, Any]]:
    review = manifest["review"]
    pointer_path = case_root / "working" / "checkpoints" / review["review_id"] / "latest.json"
    if not pointer_path.is_file():
        return []
    pointer = load_data(pointer_path)
    if (
        pointer.get("schema_version") != "mimics_checkpoint_pointer.v1"
        or pointer.get("review_id") != review["review_id"]
    ):
        raise ValidationError(f"invalid Mimics checkpoint pointer: {pointer_path}")
    checkpoint_path = ensure_within(case_root, case_root / pointer["checkpoint_manifest"])
    checkpoint = load_data(checkpoint_path)
    if (
        checkpoint.get("schema_version") != "mimics_checkpoint.v1"
        or checkpoint.get("review_id") != review["review_id"]
        or checkpoint.get("package_id") != manifest["package_id"]
    ):
        raise ValidationError(f"Mimics checkpoint does not match the current package: {checkpoint_path}")
    checkpoint_evidence_by_image = checkpoint.get("buffer_mapping_evidence_by_image_id", {})
    image_ids = sorted(
        {
            str(entry.get("image_id"))
            for entry in checkpoint.get("entries", [])
            if entry.get("image_id")
        }
    )
    expected_evidence_by_image = mapping_set.evidence_by_image_id(image_ids)
    if checkpoint_evidence_by_image:
        for image_id, expected_evidence in expected_evidence_by_image.items():
            if checkpoint_evidence_by_image.get(image_id) != expected_evidence:
                raise ValidationError(f"Mimics checkpoint buffer mapping evidence does not match image {image_id}")
    else:
        expected_evidence = str(mapping_set.default_data.get("evidence_id", ""))
        if checkpoint.get("buffer_mapping_evidence_id") != expected_evidence:
            raise ValidationError("Mimics checkpoint buffer mapping evidence does not match the workstation config")

    targets = {target["target_id"]: target for target in review["targets"]}
    expected_keys = {
        (target["target_id"], target["image_id"], organ)
        for target in review["targets"]
        for organ in target["organs"]
        if organ not in target.get("known_absent", [])
    }
    checkpoint_bases = checkpoint.get("base_labels", {})
    for target_id, target in targets.items():
        stored = checkpoint_bases.get(target_id, {})
        if (
            stored.get("label_id", "") != target.get("base_label_id", "")
            or stored.get("sha256", "") != target.get("base_label_sha256", "")
        ):
            raise ValidationError(f"Mimics checkpoint base label is stale for target {target_id}")

    entries = []
    seen = set()
    images = {image["image_id"]: image for image in manifest["image_sets"]}
    for entry in checkpoint.get("entries", []):
        key = (entry.get("target_id"), entry.get("image_id"), entry.get("organ"))
        if key not in expected_keys or key in seen:
            raise ValidationError(f"invalid or duplicate Mimics checkpoint entry: {key}")
        seen.add(key)
        if entry.get("path_base") != "package_root":
            raise ValidationError(f"Mimics checkpoint path_base must be package_root: {key}")
        path = ensure_within(case_root, case_root / entry["path"])
        if not path.is_file() or prefixed_sha256(path) != entry.get("sha256"):
            raise ValidationError(f"Mimics checkpoint buffer is missing or changed: {path}")
        axes = [int(value) for value in mapping_set.data_for_image(key[1])["platform_to_mimics_axes"]]
        expected_shape = [int(images[key[1]]["shape"][axis]) for axis in axes]
        if [int(value) for value in entry["mimics_shape"]] != expected_shape:
            raise ValidationError(f"Mimics checkpoint shape mismatch: {key}")
        if entry.get("byte_count") != path.stat().st_size:
            raise ValidationError(f"Mimics checkpoint byte count mismatch: {key}")
        if entry.get("compression") == "gzip":
            if entry.get("uncompressed_byte_count") != voxel_count(expected_shape):
                raise ValidationError(f"Mimics checkpoint uncompressed byte count mismatch: {key}")
        elif path.stat().st_size != voxel_count(expected_shape):
            raise ValidationError(f"Mimics checkpoint raw byte count mismatch: {key}")
        entries.append({**entry, "path": str(path)})
    if seen != expected_keys:
        raise ValidationError(f"Mimics checkpoint is incomplete; missing {sorted(expected_keys - seen)}")
    return entries


def prepare_case(
    case_root: Path,
    workstation_config_path: Path,
    *,
    rebuild_workspace: bool = False,
) -> Path:
    case_root = case_root.resolve()
    report = validate_case_package(case_root)
    if report["status"] != "passed":
        errors = [item for item in report["findings"] if item["severity"] == "error"]
        raise ValidationError("case package validation failed:\n- " + "\n- ".join(item["message"] for item in errors))

    manifest = json.loads((case_root / "manifest.json").read_text(encoding="utf-8"))
    config = load_workstation_config(workstation_config_path)
    mapping_set = BufferMappingSet.from_config(config)

    existing_mcs = case_root / "working" / f"{manifest['review']['review_id']}.mcs"
    prebuilt_marker = case_root / "working" / "prebuilt_workspace.json"
    if rebuild_workspace and existing_mcs.exists():
        backup = existing_mcs.with_name(existing_mcs.name + f".backup.{uuid.uuid4().hex[:8]}")
        existing_mcs.replace(backup)
        if prebuilt_marker.exists():
            prebuilt_marker.unlink()
    image_sets = []
    for image in manifest["image_sets"]:
        dicom_path = image.get("dicom_path")
        image_path = image.get("image_path")
        if not image_path:
            mimics_import = image.get("mimics_import", {})
            image_path = mimics_import.get("source_image_path")
        if not dicom_path and not existing_mcs.exists():
            raise ConfigurationError(
                f"Mimics 21 production path requires image_sets[].dicom_path or an existing .mcs; "
                f"image {image['image_id']} has neither. For NIfTI/MHD, create a Mimics package with derived DICOM first."
            )
        image_sets.append(
            {
                "image_id": image["image_id"],
                "modality": image.get("modality", "UNKNOWN"),
                "dicom_path": str((case_root / dicom_path).resolve()) if dicom_path else None,
                "image_path": str((case_root / image_path).resolve()) if image_path else None,
                "platform_shape": image["shape"],
                "spacing": image["spacing"],
                "origin": image["origin"],
                "direction": image["direction"],
                "coordinate_system": image["coordinate_system"],
                "dicom_series_uid_sha256": image.get("dicom_series_uid_sha256"),
                "series_description": image.get("series_description", ""),
            }
        )

    runtime_mode = "new"
    if existing_mcs.exists():
        runtime_mode = "prebuilt" if prebuilt_marker.is_file() else "resume"
    runtime = {
        "schema_version": "mimics_runtime.v1",
        "created_at": utc_now(),
        "package_root": str(case_root),
        "package_id": manifest["package_id"],
        "case_id": manifest["case_id"],
        "review_id": manifest["review"]["review_id"],
        "assignee": manifest["review"].get("assignee"),
        "mcs_path": str(existing_mcs),
        "mode": runtime_mode,
        "prebuilt_marker_path": str(prebuilt_marker),
        "dicom_import_root": str((case_root / "images").resolve()),
        "image_sets": image_sets,
        "targets": [
            {
                **target,
                "masks": [
                    {
                        "organ": organ,
                        "name": _runtime_mask_name(target["target_id"], organ),
                    }
                    for organ in target["organs"]
                    if organ not in target.get("known_absent", [])
                ],
            }
            for target in manifest["review"]["targets"]
        ],
        "buffer_mapping": mapping_set.default_data,
        "buffer_mapping_by_image_id": mapping_set.by_image_id,
        "mimics_compatibility": {
            "expected_product": config.get("expected_product"),
            "expected_version": config.get("expected_version"),
            "edition": config.get("edition"),
            "buffer_mapping_evidence_id": mapping_set.default_data.get("evidence_id"),
        },
        "predefined_dialog_answers": config.get("predefined_dialog_answers", {}),
        "reports_dir": str((case_root / "reports").resolve()),
        "submissions_dir": str((case_root / "submissions" / manifest["review"]["review_id"]).resolve()),
    }
    entries = prepare_import_buffers(case_root, runtime, mapping_set)
    runtime["import_buffers"] = entries
    runtime["checkpoint_buffers"] = (
            _load_checkpoint_buffers(case_root, manifest, mapping_set)
        if not existing_mcs.exists()
        else []
    )
    buffer_manifest = write_buffer_manifest(case_root, runtime, entries)
    runtime["buffer_manifest"] = str(buffer_manifest.resolve())
    runtime_path = case_root / "working" / "mimics_runtime.json"
    write_json(runtime_path, runtime)
    return runtime_path
