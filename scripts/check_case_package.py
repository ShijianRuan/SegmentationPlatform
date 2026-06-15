#!/usr/bin/env python3
"""Validate a Case Package v0.5 directory against the current contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_FILES = [
    "anatomy_vocabulary.yaml",
    "review_label_map.yaml",
]

REVIEW_STATUSES = {"ready", "in_progress", "needs_review", "completed", "blocked"}
SUBMISSION_ACTIONS = {
    "save_progress",
    "submit_complete",
    "submit_for_review",
    "report_blocked",
}
LABEL_STATE_FILENAMES = {
    "source_label.nii.gz",
    "candidate_label.nii.gz",
    "draft_label.nii.gz",
}
LEGACY_LABEL_FILENAMES = LABEL_STATE_FILENAMES | {
    "accepted_pseudo_label.nii.gz",
    "verified_label.nii.gz",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")


@dataclass
class Finding:
    level: str
    code: str
    message: str


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - CLI diagnostic should include raw parse error.
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "JSON root must be an object"
    return payload, None


def read_checksums(path: Path) -> tuple[dict[str, str], list[str]]:
    checksums: dict[str, str] = {}
    malformed: list[str] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            malformed.append(f"line {line_no}: {raw_line}")
            continue
        digest, rel_path = parts
        checksums[rel_path.strip()] = digest.strip()
    return checksums, malformed


def is_nifti(path: Path) -> bool:
    return path.name.endswith(".nii") or path.name.endswith(".nii.gz")


def nifti_stem(path: Path) -> str:
    if path.name.endswith(".nii.gz"):
        return path.name[:-7]
    if path.name.endswith(".nii"):
        return path.name[:-4]
    return path.stem


def validate_id(value: Any, field: str, findings: list[Finding]) -> str | None:
    if not isinstance(value, str) or not value:
        findings.append(Finding("error", "identifier_missing", f"{field} is required"))
        return None
    if not ID_PATTERN.fullmatch(value):
        findings.append(
            Finding(
                "error",
                "identifier_invalid",
                f"{field} must contain only letters, digits, '.', '_' or '-': {value}",
            )
        )
        return None
    return value


def resolve_package_path(
    root: Path,
    value: Any,
    field: str,
    findings: list[Finding],
) -> Path | None:
    if not isinstance(value, str) or not value:
        findings.append(Finding("error", "path_missing", f"{field} must be a non-empty relative path"))
        return None

    rel_path = Path(value)
    if rel_path.is_absolute():
        findings.append(Finding("error", "path_absolute", f"{field} must be relative: {value}"))
        return None

    resolved = (root / rel_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        findings.append(Finding("error", "path_outside_package", f"{field} escapes the case package: {value}"))
        return None
    return resolved


def validate_vector(
    value: Any,
    field: str,
    findings: list[Finding],
    *,
    integer: bool,
) -> None:
    valid_types = (int,) if integer else (int, float)
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(isinstance(item, valid_types) and not isinstance(item, bool) and item > 0 for item in value)
    ):
        kind = "positive integers" if integer else "positive numbers"
        findings.append(Finding("error", "geometry_vector_invalid", f"{field} must contain three {kind}"))


def validate_numeric_vector(value: Any, field: str, length: int, findings: list[Finding]) -> None:
    if (
        not isinstance(value, list)
        or len(value) != length
        or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value)
    ):
        findings.append(
            Finding("error", "geometry_vector_invalid", f"{field} must contain {length} numeric values")
        )


def validate_sha256(value: Any, field: str, findings: list[Finding], *, placeholder_allowed: bool) -> None:
    if value == "TO_BE_FILLED" and placeholder_allowed:
        findings.append(Finding("warning", "sha256_placeholder", f"{field} still contains TO_BE_FILLED"))
        return
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        findings.append(
            Finding(
                "error",
                "sha256_invalid",
                f"{field} must be a 64-character SHA-256 digest"
                + (" or TO_BE_FILLED" if placeholder_allowed else ""),
            )
        )


def normalized_sha256(value: str) -> str:
    return value[7:] if value.startswith("sha256:") else value


def validate_image_layout(
    root: Path,
    resolved: Path | None,
    image_id: str | None,
    field: str,
    findings: list[Finding],
    *,
    dicom: bool,
) -> None:
    if not resolved or not image_id:
        return

    expected_root = root / "images" / image_id
    try:
        relative = resolved.relative_to(expected_root)
    except ValueError:
        findings.append(
            Finding(
                "error",
                "manifest_image_layout_mismatch",
                f"{field} must be under images/{image_id}/",
            )
        )
        return

    if dicom and (not relative.parts or relative.parts[0] != "dicom"):
        findings.append(
            Finding(
                "error",
                "manifest_dicom_layout_mismatch",
                f"{field} must reference images/{image_id}/dicom or a directory below it",
            )
        )


def validate_manifest(root: Path, findings: list[Finding]) -> dict[str, Any] | None:
    manifest_path = root / "manifest.json"
    manifest, error = read_json(manifest_path)
    if error:
        findings.append(Finding("error", "manifest_invalid_json", f"manifest.json is invalid: {error}"))
        return None

    required_keys = [
        "schema_version",
        "package_id",
        "case_id",
        "leakage_group_id",
        "study_id",
        "data_governance",
        "created_at",
        "config_ref",
        "config_sha256",
        "image_sets",
        "review",
    ]
    for key in required_keys:
        if key not in manifest:
            findings.append(Finding("error", "manifest_missing_field", f"manifest.json missing required field: {key}"))

    if manifest.get("schema_version") != "case_package.v0.5":
        findings.append(
            Finding(
                "error",
                "manifest_schema_version",
                "manifest.schema_version must be case_package.v0.5",
            )
        )

    validate_id(manifest.get("package_id"), "manifest.package_id", findings)
    validate_id(manifest.get("case_id"), "manifest.case_id", findings)
    validate_id(manifest.get("leakage_group_id"), "manifest.leakage_group_id", findings)
    validate_id(manifest.get("study_id"), "manifest.study_id", findings)
    if not isinstance(manifest.get("created_at"), str) or not manifest.get("created_at"):
        findings.append(Finding("error", "manifest_created_at_missing", "manifest.created_at is required"))

    data_governance = manifest.get("data_governance")
    if not isinstance(data_governance, dict):
        findings.append(
            Finding(
                "error",
                "manifest_data_governance_type",
                "manifest.data_governance must be an object",
            )
        )
    elif data_governance.get("deidentification_status") != "verified":
        findings.append(
            Finding(
                "error",
                "manifest_deidentification_unverified",
                "manifest.data_governance.deidentification_status must be verified",
            )
        )
    else:
        for key in ("profile", "profile_version"):
            if not data_governance.get(key):
                findings.append(
                    Finding(
                        "error",
                        "manifest_data_governance_field_missing",
                        f"manifest.data_governance.{key} is required",
                    )
                )

    config_ref = manifest.get("config_ref")
    if config_ref and Path(str(config_ref)).is_absolute():
        findings.append(
            Finding(
                "error",
                "manifest_config_ref_absolute",
                "manifest.config_ref must be a relative path",
            )
        )

    config_sha256 = manifest.get("config_sha256")
    if config_sha256 is not None and not isinstance(config_sha256, dict):
        findings.append(
            Finding(
                "error",
                "manifest_config_sha_type",
                "manifest.config_sha256 must be an object",
            )
        )

    image_sets = manifest.get("image_sets")
    image_ids: set[str] = set()
    if not isinstance(image_sets, list) or not image_sets:
        findings.append(
            Finding(
                "error",
                "manifest_image_sets_type",
                "manifest.image_sets must be a non-empty array",
            )
        )
    else:
        for index, image in enumerate(image_sets):
            prefix = f"manifest.image_sets[{index}]"
            if not isinstance(image, dict):
                findings.append(Finding("error", "manifest_image_type", f"{prefix} must be an object"))
                continue

            image_id = validate_id(image.get("image_id"), f"{prefix}.image_id", findings)
            if image_id and image_id in image_ids:
                findings.append(
                    Finding("error", "manifest_image_id_duplicate", f"duplicate image_id: {image_id}")
                )
            elif image_id:
                image_ids.add(image_id)

            if not isinstance(image.get("modality"), str) or not image.get("modality"):
                findings.append(Finding("error", "manifest_image_modality_missing", f"{prefix}.modality is required"))

            image_path = image.get("image_path")
            dicom_path = image.get("dicom_path")
            if not image_path and not dicom_path:
                findings.append(
                    Finding(
                        "error",
                        "manifest_image_missing_path",
                        f"{prefix} must include image_path or dicom_path",
                    )
                )
            resolved_image = None
            if image_path:
                resolved_image = resolve_package_path(root, image_path, f"{prefix}.image_path", findings)
                validate_image_layout(
                    root,
                    resolved_image,
                    image_id,
                    f"{prefix}.image_path",
                    findings,
                    dicom=False,
                )
                if resolved_image and not resolved_image.is_file():
                    findings.append(
                        Finding(
                            "error",
                            "manifest_image_file_missing",
                            f"{prefix}.image_path does not exist: {image_path}",
                        )
                    )
            if dicom_path:
                resolved_dicom = resolve_package_path(root, dicom_path, f"{prefix}.dicom_path", findings)
                validate_image_layout(
                    root,
                    resolved_dicom,
                    image_id,
                    f"{prefix}.dicom_path",
                    findings,
                    dicom=True,
                )
                if resolved_dicom and not resolved_dicom.is_dir():
                    findings.append(
                        Finding(
                            "error",
                            "manifest_dicom_missing",
                            f"{prefix}.dicom_path is not a directory: {dicom_path}",
                        )
                    )

            validate_vector(image.get("shape"), f"{prefix}.shape", findings, integer=True)
            validate_vector(image.get("spacing"), f"{prefix}.spacing", findings, integer=False)
            validate_numeric_vector(image.get("origin"), f"{prefix}.origin", 3, findings)
            validate_numeric_vector(image.get("direction"), f"{prefix}.direction", 9, findings)
            if image.get("coordinate_system") not in {"LPS", "RAS"}:
                findings.append(
                    Finding(
                        "error",
                        "geometry_coordinate_system_invalid",
                        f"{prefix}.coordinate_system must be LPS or RAS",
                    )
                )

            if "sha256" not in image:
                findings.append(Finding("error", "manifest_image_sha_missing", f"{prefix}.sha256 is required"))
            else:
                validate_sha256(image.get("sha256"), f"{prefix}.sha256", findings, placeholder_allowed=True)

            if (
                resolved_image
                and resolved_image.is_file()
                and image.get("sha256")
                and image.get("sha256") != "TO_BE_FILLED"
                and SHA256_PATTERN.fullmatch(str(image.get("sha256")))
            ):
                expected_digest = normalized_sha256(str(image["sha256"]))
                actual_digest = sha256_file(resolved_image)
                if actual_digest.lower() != expected_digest.lower():
                    findings.append(
                        Finding(
                            "error",
                            "manifest_image_sha_mismatch",
                            f"{prefix}.image_path sha256 mismatch: "
                            f"expected {image.get('sha256')}, got {actual_digest}",
                        )
                    )

            if (
                dicom_path
                and resolved_dicom
                and resolved_dicom.is_dir()
                and image.get("sha256")
                and image.get("sha256") != "TO_BE_FILLED"
                and SHA256_PATTERN.fullmatch(str(image.get("sha256")))
            ):
                expected_digest = normalized_sha256(str(image["sha256"]))
                actual_digest = sha256_directory(resolved_dicom)
                if actual_digest.lower() != expected_digest.lower():
                    findings.append(
                        Finding(
                            "error",
                            "manifest_dicom_sha_mismatch",
                            f"{prefix}.dicom_path sha256 mismatch: "
                            f"expected {image.get('sha256')}, got {actual_digest}",
                        )
                    )

    review = manifest.get("review")
    if not isinstance(review, dict):
        findings.append(Finding("error", "manifest_review_type", "manifest.review must be an object"))
        return manifest

    for key in ("review_id", "tool", "status", "targets"):
        if not review.get(key):
            findings.append(
                Finding(
                    "error",
                    "manifest_review_field_missing",
                    f"manifest.review.{key} is required",
                )
            )

    if review.get("status") not in REVIEW_STATUSES:
        findings.append(
            Finding(
                "error",
                "manifest_review_status",
                f"manifest.review.status must be one of: {', '.join(sorted(REVIEW_STATUSES))}",
            )
        )

    targets = review.get("targets")
    if not isinstance(targets, list) or not targets:
        findings.append(
            Finding(
                "error",
                "manifest_review_targets_type",
                "manifest.review.targets must be a non-empty array",
            )
        )
    else:
        seen_target_ids: set[str] = set()
        for index, target in enumerate(targets):
            prefix = f"manifest.review.targets[{index}]"
            if not isinstance(target, dict):
                findings.append(Finding("error", "manifest_target_type", f"{prefix} must be an object"))
                continue

            target_id = validate_id(target.get("target_id"), f"{prefix}.target_id", findings)
            if target_id and target_id in seen_target_ids:
                findings.append(
                    Finding(
                        "error",
                        "manifest_target_id_duplicate",
                        f"duplicate target_id: {target_id}",
                    )
                )
            elif target_id:
                seen_target_ids.add(target_id)

            image_id = target.get("image_id")
            if image_id not in image_ids:
                findings.append(
                    Finding(
                        "error",
                        "manifest_target_image_unknown",
                        f"{prefix}.image_id does not reference image_sets: {image_id}",
                    )
                )

            organs = target.get("organs")
            if not isinstance(organs, list) or not organs or not all(
                isinstance(item, str) and item for item in organs
            ):
                findings.append(
                    Finding(
                        "error",
                        "manifest_target_organs_type",
                        f"{prefix}.organs must be a non-empty array of organ keys",
                    )
                )
            elif len(organs) != len(set(organs)):
                findings.append(
                    Finding(
                        "error",
                        "manifest_target_organs_duplicate",
                        f"{prefix}.organs contains duplicates",
                    )
                )

            if bool(target.get("base_label_id")) != bool(target.get("base_label_sha256")):
                findings.append(
                    Finding(
                        "error",
                        "manifest_base_label_incomplete",
                        f"{prefix}.base_label_id and base_label_sha256 must both be set or omitted",
                    )
                )

    initial_labels = manifest.get("initial_labels", [])
    if not isinstance(initial_labels, list):
        findings.append(
            Finding("error", "manifest_initial_labels_type", "manifest.initial_labels must be an array")
        )
    else:
        seen_initial: set[tuple[str, str]] = set()
        for index, label in enumerate(initial_labels):
            prefix = f"manifest.initial_labels[{index}]"
            if not isinstance(label, dict):
                findings.append(Finding("error", "manifest_initial_label_type", f"{prefix} must be an object"))
                continue
            image_id = label.get("image_id")
            organ = label.get("organ")
            if image_id not in image_ids:
                findings.append(
                    Finding("error", "manifest_initial_label_image_unknown", f"{prefix}.image_id is unknown")
                )
            if not isinstance(organ, str) or not ID_PATTERN.fullmatch(organ):
                findings.append(
                    Finding("error", "manifest_initial_label_organ_invalid", f"{prefix}.organ is invalid")
                )
            elif (image_id, organ) in seen_initial:
                findings.append(
                    Finding("error", "manifest_initial_label_duplicate", f"duplicate initial label: {image_id}/{organ}")
                )
            else:
                seen_initial.add((image_id, organ))
            resolved_label = resolve_package_path(root, label.get("path"), f"{prefix}.path", findings)
            if resolved_label and not resolved_label.is_file():
                findings.append(
                    Finding("error", "manifest_initial_label_missing", f"{prefix}.path does not exist")
                )
            validate_sha256(label.get("sha256"), f"{prefix}.sha256", findings, placeholder_allowed=False)
            if (
                resolved_label
                and resolved_label.is_file()
                and isinstance(label.get("sha256"), str)
                and SHA256_PATTERN.fullmatch(label["sha256"])
                and sha256_file(resolved_label).lower() != normalized_sha256(label["sha256"]).lower()
            ):
                findings.append(
                    Finding("error", "manifest_initial_label_sha_mismatch", f"{prefix}.sha256 does not match the file")
                )

    return manifest


def manifest_indexes(manifest: dict[str, Any] | None) -> tuple[set[str], dict[str, dict[str, Any]]]:
    image_ids: set[str] = set()
    targets: dict[str, dict[str, Any]] = {}
    if not manifest:
        return image_ids, targets

    for image in manifest.get("image_sets", []):
        if isinstance(image, dict) and isinstance(image.get("image_id"), str):
            image_ids.add(image["image_id"])

    review = manifest.get("review")
    if isinstance(review, dict):
        for target in review.get("targets", []):
            if isinstance(target, dict) and isinstance(target.get("target_id"), str):
                targets[target["target_id"]] = target
    return image_ids, targets


def validate_label_inputs(
    root: Path,
    findings: list[Finding],
    manifest: dict[str, Any] | None,
) -> None:
    labels_root = root / "labels"
    if not labels_root.exists():
        return
    if not labels_root.is_dir():
        findings.append(Finding("error", "labels_not_directory", "labels must be a directory"))
        return

    image_ids, targets = manifest_indexes(manifest)
    target_organs_by_image: dict[str, set[str]] = {}
    for target in targets.values():
        image_id = target.get("image_id")
        organs = target.get("organs")
        if isinstance(image_id, str) and isinstance(organs, list):
            target_organs_by_image.setdefault(image_id, set()).update(
                organ for organ in organs if isinstance(organ, str)
            )

    for entry in sorted(labels_root.iterdir()):
        if entry.is_file() or entry.name == "masks":
            if entry.name in LEGACY_LABEL_FILENAMES or entry.name == "masks":
                findings.append(
                    Finding(
                        "error",
                        "legacy_label_layout",
                        f"v0.5 requires labels/{{image_id}}/...; legacy path found: {entry.relative_to(root)}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "error",
                        "unexpected_labels_entry",
                        f"unexpected entry under labels/: {entry.relative_to(root)}",
                    )
                )
            continue

        if not entry.is_dir():
            findings.append(
                Finding("error", "unexpected_labels_entry", f"unexpected entry under labels/: {entry.relative_to(root)}")
            )
            continue
        if entry.name not in image_ids:
            findings.append(
                Finding(
                    "error",
                    "label_image_unknown",
                    f"label directory does not reference manifest.image_sets: {entry.relative_to(root)}",
                )
            )
            continue

        for item in sorted(entry.iterdir()):
            if item.is_file():
                if item.name not in LABEL_STATE_FILENAMES:
                    findings.append(
                        Finding(
                            "error",
                            "unexpected_label_file",
                            f"unsupported v0.5 label file: {item.relative_to(root)}",
                        )
                    )
                continue

            if item.is_dir() and item.name == "masks":
                for mask in sorted(item.iterdir()):
                    if not mask.is_file() or not is_nifti(mask):
                        findings.append(
                            Finding(
                                "error",
                                "mask_file_invalid",
                                f"mask must be a .nii or .nii.gz file: {mask.relative_to(root)}",
                            )
                        )
                        continue
                    organ = nifti_stem(mask)
                    if not ID_PATTERN.fullmatch(organ):
                        findings.append(
                            Finding(
                                "error",
                                "mask_organ_invalid",
                                f"mask filename must be a canonical organ key: {mask.relative_to(root)}",
                            )
                        )
                    elif organ not in target_organs_by_image.get(entry.name, set()):
                        findings.append(
                            Finding(
                                "warning",
                                "mask_not_in_review_targets",
                                f"mask is not requested by any review target for {entry.name}: {organ}",
                            )
                        )
                continue

            findings.append(
                Finding(
                    "error",
                    "unexpected_label_directory",
                    f"unsupported directory under labels/{entry.name}: {item.relative_to(root)}",
                )
            )


def output_exists(submission_dir: Path, target_id: str, image_id: str, organ: str) -> bool:
    return any(
        path.is_file()
        for path in (
            submission_dir / "buffers" / image_id / f"{organ}.npy",
            submission_dir / "buffers" / image_id / target_id / f"{organ}.u8",
            submission_dir / "labels" / image_id / f"{organ}.nii",
            submission_dir / "labels" / image_id / f"{organ}.nii.gz",
            submission_dir / "labels" / image_id / target_id / f"{organ}.nii",
            submission_dir / "labels" / image_id / target_id / f"{organ}.nii.gz",
        )
    )


def validate_submissions(
    root: Path,
    findings: list[Finding],
    manifest: dict[str, Any] | None,
) -> None:
    submissions_root = root / "submissions"
    if not submissions_root.exists():
        return
    if not submissions_root.is_dir():
        findings.append(Finding("error", "submissions_not_directory", "submissions must be a directory"))
        return
    if not manifest or not isinstance(manifest.get("review"), dict):
        return

    review = manifest["review"]
    expected_review_id = review.get("review_id")
    expected_assignee = review.get("assignee")
    _, targets = manifest_indexes(manifest)

    for submission_dir in sorted(submissions_root.iterdir()):
        if not submission_dir.is_dir():
            findings.append(
                Finding(
                    "error",
                    "unexpected_submission_entry",
                    f"submissions may only contain review directories: {submission_dir.relative_to(root)}",
                )
            )
            continue
        if submission_dir.name != expected_review_id:
            findings.append(
                Finding(
                    "error",
                    "submission_review_directory_mismatch",
                    f"submission directory must match manifest.review.review_id: {submission_dir.relative_to(root)}",
                )
            )

        submission_path = submission_dir / "submission_manifest.json"
        if not submission_path.is_file():
            findings.append(
                Finding(
                    "error",
                    "submission_manifest_missing",
                    f"missing submission manifest: {submission_path.relative_to(root)}",
                )
            )
            continue

        submission, error = read_json(submission_path)
        if error:
            findings.append(
                Finding(
                    "error",
                    "submission_manifest_invalid",
                    f"{submission_path.relative_to(root)} is invalid: {error}",
                )
            )
            continue
        assert submission is not None

        if submission.get("schema_version") != "review_submission.v1":
            findings.append(
                Finding(
                    "error",
                    "submission_schema_version",
                    "submission_manifest.schema_version must be review_submission.v1",
                )
            )
        if submission.get("review_id") != expected_review_id:
            findings.append(
                Finding(
                    "error",
                    "submission_review_id_mismatch",
                    "submission_manifest.review_id does not match manifest.review.review_id",
                )
            )

        action = submission.get("action")
        if action not in SUBMISSION_ACTIONS:
            findings.append(
                Finding(
                    "error",
                    "submission_action_invalid",
                    f"submission_manifest.action must be one of: {', '.join(sorted(SUBMISSION_ACTIONS))}",
                )
            )

        if expected_assignee and submission.get("assignee") != expected_assignee:
            findings.append(
                Finding(
                    "error",
                    "submission_assignee_mismatch",
                    "submission_manifest.assignee does not match manifest.review.assignee",
                )
            )

        target_ids = submission.get("target_ids")
        if (
            not isinstance(target_ids, list)
            or not target_ids
            or not all(isinstance(target_id, str) and target_id for target_id in target_ids)
        ):
            findings.append(
                Finding(
                    "error",
                    "submission_target_ids_invalid",
                    "submission_manifest.target_ids must be a non-empty array",
                )
            )
            continue
        if len(target_ids) != len(set(target_ids)):
            findings.append(
                Finding("error", "submission_target_ids_duplicate", "submission_manifest.target_ids contains duplicates")
            )

        base_labels = submission.get("base_labels", {})
        if not isinstance(base_labels, dict):
            findings.append(
                Finding("error", "submission_base_labels_invalid", "submission_manifest.base_labels must be an object")
            )
            base_labels = {}

        for target_id in target_ids:
            target = targets.get(target_id)
            if not target:
                findings.append(
                    Finding(
                        "error",
                        "submission_target_unknown",
                        f"submission target does not exist in manifest.review.targets: {target_id}",
                    )
                )
                continue

            expected_label_id = target.get("base_label_id")
            expected_label_sha = target.get("base_label_sha256")
            submitted_base = base_labels.get(target_id)
            if expected_label_id or expected_label_sha:
                if not isinstance(submitted_base, dict):
                    findings.append(
                        Finding(
                            "error",
                            "submission_base_label_missing",
                            f"submission base_labels is missing target: {target_id}",
                        )
                    )
                elif (
                    submitted_base.get("label_id") != expected_label_id
                    or submitted_base.get("sha256") != expected_label_sha
                ):
                    findings.append(
                        Finding(
                            "error",
                            "submission_base_label_mismatch",
                            f"submission base label does not match the review task: {target_id}",
                        )
                    )

            if action in {"submit_complete", "submit_for_review"}:
                image_id = target.get("image_id")
                for organ in target.get("organs", []):
                    if isinstance(image_id, str) and isinstance(organ, str) and not output_exists(
                        submission_dir, target_id, image_id, organ
                    ):
                        findings.append(
                            Finding(
                                "error",
                                "submission_output_missing",
                                f"completed target {target_id} is missing output for {image_id}/{organ}",
                            )
                        )

    if any(submissions_root.iterdir()):
        for rel_path in ("reports/review_report.json", "provenance/tool_export.json"):
            if not (root / rel_path).is_file():
                findings.append(
                    Finding(
                        "warning",
                        "submission_evidence_pending",
                        f"submission evidence is not present yet; finalize may still be pending or failed: {rel_path}",
                    )
                )


def validate_required_files(
    root: Path,
    findings: list[Finding],
    manifest: dict[str, Any] | None,
) -> None:
    if not (root / "manifest.json").is_file():
        findings.append(Finding("error", "required_file_missing", "missing required file: manifest.json"))

    if not manifest or not manifest.get("config_ref"):
        return

    config_dir = (root / str(manifest["config_ref"])).resolve()
    if not config_dir.is_dir():
        findings.append(
            Finding(
                "error",
                "config_ref_missing",
                f"manifest.config_ref does not resolve to a directory: {manifest['config_ref']}",
            )
        )
        return

    config_hashes = manifest.get("config_sha256")
    if not isinstance(config_hashes, dict):
        config_hashes = {}

    for filename in REQUIRED_CONFIG_FILES:
        config_path = config_dir / filename
        if not config_path.is_file():
            findings.append(
                Finding(
                    "error",
                    "required_config_missing",
                    f"missing required shared config: "
                    f"{str(manifest['config_ref']).rstrip('/')}/{filename}",
                )
            )
            continue

        expected_digest = config_hashes.get(filename)
        if not expected_digest:
            findings.append(
                Finding(
                    "error",
                    "config_sha_missing",
                    f"manifest.config_sha256 missing digest for: {filename}",
                )
            )
        else:
            validate_sha256(
                expected_digest,
                f"manifest.config_sha256.{filename}",
                findings,
                placeholder_allowed=True,
            )
            if expected_digest == "TO_BE_FILLED" or not SHA256_PATTERN.fullmatch(str(expected_digest)):
                continue
            actual_digest = sha256_file(config_path)
            normalized_digest = normalized_sha256(str(expected_digest))
            if actual_digest.lower() != normalized_digest.lower():
                findings.append(
                    Finding(
                        "error",
                        "config_sha_mismatch",
                        f"shared config sha256 mismatch for {filename}: "
                        f"expected {expected_digest}, got {actual_digest}",
                    )
                )


def validate_checksums(root: Path, findings: list[Finding]) -> None:
    checksum_path = root / "checksums.sha256"
    if not checksum_path.is_file():
        return

    checksums, malformed = read_checksums(checksum_path)
    for line in malformed:
        findings.append(Finding("error", "checksum_malformed", f"malformed checksum entry: {line}"))

    for rel_path, expected_digest in checksums.items():
        path = resolve_package_path(root, rel_path, f"checksums.sha256[{rel_path}]", findings)
        if not SHA256_PATTERN.fullmatch(expected_digest):
            findings.append(
                Finding(
                    "error",
                    "checksum_digest_invalid",
                    f"checksum entry is not a SHA-256 digest: {rel_path}",
                )
            )
            continue
        if not path:
            continue
        if not path.is_file():
            findings.append(Finding("error", "checksum_file_missing", f"checksum references missing file: {rel_path}"))
            continue
        actual_digest = sha256_file(path)
        normalized_digest = normalized_sha256(expected_digest)
        if actual_digest.lower() != normalized_digest.lower():
            findings.append(
                Finding(
                    "error",
                    "checksum_mismatch",
                    f"checksum mismatch for {rel_path}: expected {expected_digest}, got {actual_digest}",
                )
            )


def build_report(root: Path, findings: list[Finding], manifest: dict[str, Any] | None) -> dict[str, Any]:
    status = "passed" if not any(item.level == "error" for item in findings) else "failed"
    return {
        "schema_version": "case_package_preflight/v0.5",
        "package_dir": str(root),
        "status": status,
        "case_id": manifest.get("case_id") if manifest else None,
        "package_id": manifest.get("package_id") if manifest else None,
        "findings": [item.__dict__ for item in findings],
    }


def validate_case_package(root: Path) -> dict[str, Any]:
    root = root.resolve()
    findings: list[Finding] = []
    manifest = validate_manifest(root, findings) if (root / "manifest.json").is_file() else None
    validate_required_files(root, findings, manifest)
    validate_label_inputs(root, findings, manifest)
    validate_submissions(root, findings, manifest)
    validate_checksums(root, findings)
    return build_report(root, findings, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--json-output", type=Path, help="Optional path for preflight_report.json.")
    args = parser.parse_args()

    root = args.package_dir.resolve()
    if not root.is_dir():
        parser.error(f"package_dir is not a directory: {root}")

    report = validate_case_package(root)

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_output:
        args.json_output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
