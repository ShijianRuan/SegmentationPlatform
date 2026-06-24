from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from segplatform.common import (
    canonical_id,
    copy_path,
    ensure_within,
    hash_directory,
    load_data,
    prefixed_sha256,
    sha256_file,
    utc_now,
    write_json,
    write_yaml,
)
from segplatform.errors import ValidationError
from segplatform.imaging import (
    Geometry,
    geometry_matches,
    infer_format,
    inspect_dicom_files,
    inspect_image,
    read_mask,
    write_derived_dicom_series,
    write_mask_nifti,
)
from segplatform.registry import FileRegistry
from segplatform.schema import repository_root, validate_schema
from segplatform.vocabulary import AnatomyVocabulary


def _copy_dicom_file_set(source_root: Path, relative_files: list[str], destination: Path, *, copy_mode: str) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative in relative_files:
        source_file = ensure_within(source_root, source_root / relative)
        if not source_file.is_file():
            raise ValidationError(f"DICOM source file does not exist: {source_file}")
        target = ensure_within(destination, destination / relative)
        copy_path(source_file, target, mode=copy_mode)


def _copy_image(
    source: Path,
    image_root: Path,
    format_name: str,
    *,
    source_files: list[str] | None = None,
    companion_paths: list[str] | None = None,
    copy_mode: str = "copy",
) -> tuple[Path, str]:
    if format_name == "dicom_series":
        destination = image_root / "dicom"
        if source_files:
            _copy_dicom_file_set(source, source_files, destination, copy_mode=copy_mode)
        else:
            copy_path(source, destination, mode=copy_mode)
        return destination, "dicom_path"
    if format_name == "nifti":
        suffix = ".nii.gz" if source.name.lower().endswith(".nii.gz") else ".nii"
        destination = image_root / ("image" + suffix)
        copy_path(source, destination, mode=copy_mode)
        return destination, "image_path"
    if format_name == "metaimage":
        destination = image_root / source.name
        copy_path(source, destination, mode=copy_mode)
        for companion_text in companion_paths or []:
            companion = Path(companion_text)
            if companion.exists():
                try:
                    companion_relative = companion.resolve().relative_to(source.parent.resolve())
                except ValueError:
                    companion_relative = Path(companion.name)
                copy_path(companion, image_root / companion_relative, mode=copy_mode)
        return destination, "image_path"
    raise ValidationError(f"unsupported image format for package creation: {format_name}")


def _image_artifact(
    request: dict[str, Any],
    *,
    case_id: str,
    image_id: str,
    format_name: str,
    package_path: Path,
    geometry: Geometry,
    inspection: dict[str, Any],
) -> dict[str, Any]:
    source = {
        "type": str(request.get("source_type", "local_import")),
        "import_batch": str(request.get("import_batch", "manual")),
        "source_layout": request.get("source_layout", {}),
        "reader": inspection["reader"],
    }
    if request.get("source_name"):
        source["name"] = str(request["source_name"])
    return {
        "schema_version": "image_artifact.v1",
        "image_id": image_id,
        "case_id": case_id,
        "modality": str(request.get("modality", "UNKNOWN")),
        "format": format_name,
        "path": str(package_path.resolve()),
        "companion_paths": inspection.get("companion_paths", []),
        "hash": inspection["hash"],
        "hash_scope": inspection["hash_scope"],
        "pixel_type": geometry.pixel_type,
        "shape": list(geometry.shape),
        "spacing": list(geometry.spacing),
        "origin": list(geometry.origin),
        "direction": list(geometry.direction),
        "geometry_status": inspection.get("geometry_status", "complete"),
        "geometry_evidence": inspection.get(
            "geometry_evidence",
            {
                "coordinate_system": geometry.coordinate_system,
                "shape": geometry.source,
                "spacing": geometry.source,
                "origin": geometry.source,
                "direction": geometry.source,
                "assumptions": [],
            },
        ),
        "source": source,
        "usability": {
            "annotation": "allowed",
            "training": "allowed",
            "evaluation": "allowed",
            "reasons": [],
        },
    }


def _write_initial_labels(
    case_root: Path,
    initial_labels: list[dict[str, Any]],
    image_geometry: dict[str, Geometry],
    vocabulary: AnatomyVocabulary,
) -> list[dict[str, Any]]:
    written = []
    for entry in initial_labels:
        image_id = canonical_id(str(entry["image_id"]), "image_id")
        if image_id not in image_geometry:
            raise ValidationError(f"initial label references unknown image_id: {image_id}")
        lifecycle_status = str(entry.get("lifecycle_status", "draft_label"))
        if lifecycle_status not in {
            "source_label",
            "candidate_label",
            "draft_label",
            "verified_label",
            "rejected_label",
        }:
            raise ValidationError(f"invalid initial label lifecycle_status: {lifecycle_status}")
        source_path = Path(entry["path"]).expanduser().resolve()
        array, label_geometry = read_mask(source_path)
        matches, reasons = geometry_matches(image_geometry[image_id], label_geometry)
        if not matches:
            raise ValidationError(
                f"initial label does not match image {image_id}: {source_path}; " + "; ".join(reasons)
            )

        if "organ" in entry:
            mappings = {vocabulary.normalize(str(entry["organ"])): 1}
            if not np.array_equal(np.unique(array), np.asarray([0, 1])) and not set(np.unique(array)).issubset({0, 1}):
                raise ValidationError(f"single-organ mask must contain only 0/1: {source_path}")
        else:
            raw_map = entry.get("label_map")
            if not isinstance(raw_map, dict) or not raw_map:
                raise ValidationError("initial label requires either organ or non-empty label_map")
            mappings = {vocabulary.normalize(str(organ)): int(value) for organ, value in raw_map.items()}
            unknown_values = set(int(value) for value in np.unique(array)) - {0, *mappings.values()}
            if unknown_values:
                raise ValidationError(f"initial multilabel contains unknown values {sorted(unknown_values)}: {source_path}")

        masks_root = case_root / "labels" / image_id / "masks"
        for organ, value in mappings.items():
            destination = masks_root / f"{organ}.nii.gz"
            write_mask_nifti(destination, array == value, image_geometry[image_id])
            written.append(
                {
                    "image_id": image_id,
                    "organ": organ,
                    "path": destination.relative_to(case_root).as_posix(),
                    "sha256": prefixed_sha256(destination),
                    "lifecycle_status": lifecycle_status,
                    "requested_label_id": entry.get("label_id"),
                    "generator_id": entry.get("generator_id"),
                    "source_type": entry.get("source_type"),
                    "usage_constraints": entry.get(
                        "usage_constraints",
                        {
                            "model_training": "needs_policy",
                            "commercial_use": "needs_policy",
                            "redistribution": "needs_policy",
                        },
                    ),
                }
            )
    constraint_order = {
        "allowed": 0,
        "allowed_with_policy": 1,
        "needs_policy": 2,
        "needs_review": 3,
        "forbidden": 4,
    }
    for image_id in sorted({item["image_id"] for item in written}):
        group = [item for item in written if item["image_id"] == image_id]
        requested_ids = {str(item["requested_label_id"]) for item in group if item.get("requested_label_id")}
        if len(requested_ids) > 1:
            raise ValidationError(
                f"all initial masks for image {image_id} must belong to one Label Artifact; found IDs {sorted(requested_ids)}"
            )
        bundle_hash = hash_directory(case_root / "labels" / image_id / "masks")
        label_id = next(iter(requested_ids), f"label_{image_id}_initial_{bundle_hash[7:19]}")
        constraint_keys = set().union(*(item["usage_constraints"].keys() for item in group))
        merged_constraints = {
            key: max(
                (item["usage_constraints"].get(key, "needs_policy") for item in group),
                key=lambda value: constraint_order[value],
            )
            for key in sorted(constraint_keys)
        }
        for item in group:
            item.pop("requested_label_id", None)
            item["label_id"] = label_id
            item["label_bundle_sha256"] = bundle_hash
            item["usage_constraints"] = merged_constraints
    return written


def create_case_package(
    request_path: Path,
    output_root: Path,
    *,
    registry_root: Path | None = None,
    overwrite: bool = False,
    copy_mode: str = "copy",
) -> Path:
    request = load_data(request_path)
    if request.get("schema_version") != "case_package_request.v1":
        raise ValidationError("package request schema_version must be case_package_request.v1")
    if copy_mode not in {"copy", "hardlink", "symlink"}:
        raise ValidationError(f"unsupported copy_mode: {copy_mode}")
    case_id = canonical_id(str(request["case_id"]), "case_id")
    package_id = canonical_id(str(request.get("package_id", f"pkg_{case_id}")), "package_id")
    review_request = request["review"]
    review_id = canonical_id(str(review_request["review_id"]), "review_id")
    package_root = output_root.resolve()
    case_root = package_root / "cases" / case_id
    if case_root.exists():
        if not (case_root / "manifest.json").is_file():
            shutil.rmtree(case_root)
        elif not overwrite:
            raise ValidationError(f"case package already exists: {case_root}")
        else:
            shutil.rmtree(case_root)
    if case_root.exists():
        if not overwrite:
            raise ValidationError(f"case package already exists: {case_root}")
        shutil.rmtree(case_root)
    case_root.mkdir(parents=True)

    vocabulary = AnatomyVocabulary()
    target_records = []
    image_ids = set()
    for target in review_request["targets"]:
        target_id = canonical_id(str(target["target_id"]), "target_id")
        image_id = canonical_id(str(target["image_id"]), "image_id")
        organs = vocabulary.require_all([str(item) for item in target["organs"]])
        known_absent = (
            vocabulary.require_all([str(item) for item in target["known_absent"]])
            if target.get("known_absent")
            else []
        )
        unknown_absent = set(known_absent) - set(organs)
        if unknown_absent:
            raise ValidationError(
                f"target {target_id}: known_absent must be a subset of organs; unknown: {sorted(unknown_absent)}"
            )
        target_record = {
            "target_id": target_id,
            "image_id": image_id,
            "organs": organs,
        }
        if known_absent:
            target_record["known_absent"] = known_absent
        if target.get("base_label_id") is not None or target.get("base_label_sha256") is not None:
            if not target.get("base_label_id") or not target.get("base_label_sha256"):
                raise ValidationError(f"target {target_id}: base_label_id and base_label_sha256 must appear together")
            target_record["base_label_id"] = str(target["base_label_id"])
            target_record["base_label_sha256"] = str(target["base_label_sha256"])
        target_records.append(target_record)

    image_records = []
    image_artifacts = []
    image_geometry: dict[str, Geometry] = {}
    ingest_findings = []
    for image_request in request["image_sets"]:
        source = Path(image_request["source"]).expanduser().resolve()
        if not source.exists():
            raise ValidationError(f"image source does not exist: {source}")
        image_id = canonical_id(str(image_request["image_id"]), "image_id")
        if image_id in image_ids:
            raise ValidationError(f"duplicate image_id: {image_id}")
        image_ids.add(image_id)
        format_name = str(image_request.get("format") or infer_format(source))
        source_files = image_request.get("source_files")
        if source_files:
            if format_name != "dicom_series":
                raise ValidationError(f"image {image_id}: source_files is only supported for dicom_series")
            relative_files = [str(item) for item in source_files]
            source_geometry, source_inspection = inspect_dicom_files(
                [source / relative for relative in relative_files],
                root=source,
            )
        else:
            relative_files = None
            source_geometry, source_inspection = inspect_image(source, format_name)
        copied_path, manifest_path_field = _copy_image(
            source,
            case_root / "images" / image_id,
            format_name,
            source_files=relative_files,
            companion_paths=source_inspection.get("companion_paths", []),
            copy_mode=copy_mode,
        )
        copied_geometry, copied_inspection = inspect_image(copied_path, format_name)
        matches, reasons = geometry_matches(source_geometry, copied_geometry)
        if not matches or source_inspection["hash"] != copied_inspection["hash"]:
            raise ValidationError(f"copied image verification failed for {image_id}: {'; '.join(reasons)}")
        image_geometry[image_id] = copied_geometry
        if format_name == "dicom_series":
            scan = copied_inspection["deidentification_scan"]
            allowed_tags = set(str(item) for item in image_request.get("allowed_dicom_tags", []))
            disallowed_tags = sorted(set(scan["sensitive_tags_present"]) - allowed_tags)
            strict_deidentification = bool(request.get("data_governance", {}).get("strict_deidentification", False))
            status = "passed"
            if disallowed_tags:
                status = "warning"
            burned_in = {value.upper() for value in scan["burned_in_annotation_values"] if value}
            if "YES" in burned_in:
                status = "warning"
            if strict_deidentification and disallowed_tags:
                raise ValidationError(
                    f"DICOM deidentification scan found disallowed populated tags for {image_id}: {disallowed_tags}"
                )
            if strict_deidentification and "YES" in burned_in:
                raise ValidationError(f"DICOM BurnedInAnnotation=YES requires manual review before packaging: {image_id}")
            ingest_findings.append(
                {
                    "image_id": image_id,
                    "format": format_name,
                    "sensitive_tags_present": scan["sensitive_tags_present"],
                    "allowed_exceptions": sorted(allowed_tags),
                    "patient_identity_removed_values": scan["patient_identity_removed_values"],
                    "burned_in_annotation_values": scan["burned_in_annotation_values"],
                    "status": status,
                    "strict_deidentification": strict_deidentification,
                }
            )
        manifest_record = {
            "image_id": image_id,
            "modality": str(image_request.get("modality", "UNKNOWN")),
            manifest_path_field: copied_path.relative_to(case_root).as_posix(),
            "sha256": copied_inspection["hash"],
            **copied_geometry.as_manifest(),
        }
        if str(review_request.get("tool", "mimics")) == "mimics" and format_name in {"nifti", "metaimage"}:
            derived_dicom_path = case_root / "images" / image_id / "dicom"
            derived_inspection = write_derived_dicom_series(
                copied_path,
                derived_dicom_path,
                format_name=format_name,
                modality=str(image_request.get("modality", "UNKNOWN")),
                case_id=case_id,
                study_id=str(request["study_id"]),
                series_description=str(image_request.get("series_description", f"SP derived {image_id}")),
            )
            manifest_record["dicom_path"] = derived_dicom_path.relative_to(case_root).as_posix()
            manifest_record["dicom_sha256"] = derived_inspection["hash"]
            manifest_record["mimics_import"] = {
                "strategy": "derived_dicom_series",
                "source_image_path": manifest_record[manifest_path_field],
                "source_format": format_name,
                "pixel_conversion": derived_inspection["pixel_conversion"],
            }
        for key in ("dicom_series_uid_sha256", "series_description", "study_instance_uid_sha256"):
            if key in copied_inspection:
                manifest_record[key] = copied_inspection[key]
        if "dicom_path" in manifest_record:
            derived_dicom_geometry, derived_dicom_inspection = inspect_image(
                case_root / manifest_record["dicom_path"],
                "dicom_series",
            )
            manifest_record["dicom_series_uid_sha256"] = derived_dicom_inspection["dicom_series_uid_sha256"]
            manifest_record["study_instance_uid_sha256"] = derived_dicom_inspection["study_instance_uid_sha256"]
            if "series_description" not in manifest_record:
                manifest_record["series_description"] = derived_dicom_inspection.get("series_description", "")
        image_records.append(manifest_record)
        image_artifacts.append(
            _image_artifact(
                image_request,
                case_id=case_id,
                image_id=image_id,
                format_name=format_name,
                package_path=copied_path,
                geometry=copied_geometry,
                inspection=copied_inspection,
            )
        )

    missing_images = {target["image_id"] for target in target_records} - image_ids
    if missing_images:
        raise ValidationError(f"review targets reference unknown image_ids: {sorted(missing_images)}")

    config_root = package_root / "config"
    config_root.mkdir(parents=True, exist_ok=True)
    anatomy_destination = config_root / "anatomy_vocabulary.yaml"
    if not anatomy_destination.exists():
        shutil.copy2(repository_root() / "config" / "anatomy_vocabulary.yaml", anatomy_destination)
    all_organs = sorted(vocabulary.organs)
    review_label_map = {
        "schema_version": "review_label_map.v1",
        "labels": {organ: index + 1 for index, organ in enumerate(all_organs)},
    }
    review_map_path = config_root / "review_label_map.yaml"
    write_yaml(review_map_path, review_label_map)

    initial_labels = _write_initial_labels(
        case_root,
        list(request.get("initial_labels", [])),
        image_geometry,
        vocabulary,
    )
    initial_groups: dict[str, dict[str, Any]] = {}
    for initial in initial_labels:
        group = initial_groups.setdefault(
            initial["image_id"],
            {
                "label_id": initial["label_id"],
                "label_bundle_sha256": initial["label_bundle_sha256"],
                "organs": set(),
            },
        )
        group["organs"].add(initial["organ"])
    for target in target_records:
        group = initial_groups.get(target["image_id"])
        expected_organs = set(target["organs"]) - set(target.get("known_absent", []))
        if not target.get("base_label_id") and group and expected_organs.issubset(group["organs"]):
            target["base_label_id"] = group["label_id"]
            target["base_label_sha256"] = group["label_bundle_sha256"]
    data_governance = dict(request["data_governance"])
    data_governance.setdefault("strict_deidentification", False)

    manifest = {
        "schema_version": "case_package.v0.5",
        "package_id": package_id,
        "case_id": case_id,
        "leakage_group_id": str(request["leakage_group_id"]),
        "study_id": str(request["study_id"]),
        "data_governance": data_governance,
        "created_at": utc_now(),
        "config_ref": "../../config",
        "config_sha256": {
            "anatomy_vocabulary.yaml": sha256_file(anatomy_destination),
            "review_label_map.yaml": sha256_file(review_map_path),
        },
        "image_sets": image_records,
        "initial_labels": initial_labels,
        "review": {
            "review_id": review_id,
            "tool": str(review_request.get("tool", "mimics")),
            "status": "ready",
            "assignee": review_request.get("assignee"),
            "targets": target_records,
        },
    }
    for optional in ("patient_id_hash", "study_instance_uid_hash"):
        if request.get(optional):
            manifest[optional] = request[optional]
    write_json(case_root / "manifest.json", manifest)
    for name in ("working", "submissions", "reports", "provenance"):
        (case_root / name).mkdir(exist_ok=True)
    write_json(
        case_root / "reports" / "ingest_report.json",
        {
            "schema_version": "ingest_report.v1",
            "case_id": case_id,
            "created_at": utc_now(),
            "status": "passed",
            "images": ingest_findings,
            "note": (
                "The report records tag names and policy outcomes, not original identifying values. "
                "Deidentification is governance metadata by default; set data_governance.strict_deidentification=true "
                "to make these findings block package creation."
            ),
        },
    )

    if registry_root:
        registry = FileRegistry(registry_root)
        case_record = {
            "schema_version": "case_manifest.v1",
            "case_id": case_id,
            "leakage_group_id": str(request["leakage_group_id"]),
            "leakage_group_basis": str(request.get("leakage_group_basis", "case")),
            "leakage_group_confidence": str(request.get("leakage_group_confidence", "medium")),
            "study_id": str(request["study_id"]),
            "image_ids": sorted(image_ids),
            "data_governance": data_governance,
        }
        for optional in ("patient_id_hash", "study_instance_uid_hash"):
            if request.get(optional):
                case_record[optional] = request[optional]
        registry.put("cases", case_record)
        for artifact in image_artifacts:
            registry.put("images", artifact)
        for image_id, group_info in initial_groups.items():
            group = [initial for initial in initial_labels if initial["image_id"] == image_id]
            geometry = image_geometry[image_id]
            masks_root = case_root / "labels" / image_id / "masks"
            segments = []
            for initial in group:
                lifecycle = initial["lifecycle_status"]
                if initial.get("source_type"):
                    source_type = initial["source_type"]
                elif lifecycle == "source_label":
                    source_type = "imported_dataset"
                elif lifecycle == "candidate_label":
                    source_type = "external_algorithm"
                elif lifecycle == "verified_label":
                    source_type = "manual_review"
                else:
                    source_type = "rule_script"
                segment_source = {"type": source_type}
                if initial.get("generator_id"):
                    segment_source["generator_id"] = initial["generator_id"]
                label_path = case_root / initial["path"]
                segments.append(
                    {
                        "organ": initial["organ"],
                        "path": str(label_path.resolve()),
                        "lifecycle_status": lifecycle,
                        "source": segment_source,
                        "lineage": {
                            "derived_from_label_ids": [],
                            "contributing_generators": [initial["generator_id"]]
                            if initial.get("generator_id")
                            else [],
                        },
                    }
                )
            initial_record = {
                "schema_version": "label_artifact.v1",
                "label_id": group_info["label_id"],
                "case_id": case_id,
                "image_id": image_id,
                "path": str(masks_root.resolve()),
                "format": "per_organ_masks",
                "hash": group_info["label_bundle_sha256"],
                "hash_scope": "bundle_manifest",
                "pixel_type": "uint8",
                "geometry_ref": image_id,
                "geometry": {
                    "shape": list(geometry.shape),
                    "spacing": list(geometry.spacing),
                    "origin": list(geometry.origin),
                    "direction": list(geometry.direction),
                    "geometry_status": "complete",
                    "geometry_evidence": {
                        "shape": "header",
                        "spacing": "header",
                        "origin": "header",
                        "direction": "header",
                        "assumptions": [],
                    },
                    "alignment_checked": True,
                    "alignment_basis": "physical_space",
                },
                "artifact_lifecycle": "active",
                "usage_constraints": group[0]["usage_constraints"],
                "parent_label_id": None,
                "segments": segments,
            }
            registry.put("labels", initial_record)
        review_record = {
            "schema_version": "review_task.v1",
            "review_id": review_id,
            "package_id": package_id,
            "case_id": case_id,
            "tool": str(review_request.get("tool", "mimics")),
            "status": "ready",
            "assignee": review_request.get("assignee"),
            "package_path": str(case_root),
            "created_at": utc_now(),
            "targets": [
                {
                    **target,
                    "status": "ready",
                }
                for target in target_records
            ],
            "events": [{"at": utc_now(), "action": "created", "actor": "platform"}],
        }
        registry.put("reviews", review_record)

    return case_root


def validate_case_package(case_root: Path) -> dict[str, Any]:
    import importlib.util
    import sys

    script_path = repository_root() / "scripts" / "check_case_package.py"
    spec = importlib.util.spec_from_file_location("segplatform_case_package_validator", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load case package validator: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.validate_case_package(case_root.resolve())


def validate_registry_record(path: Path, schema_name: str) -> None:
    validate_schema(load_data(path), schema_name)
