#!/usr/bin/env python3
"""Validate a Case Package v0.1 directory against the current contract draft."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_FILES = [
    "config/anatomy_vocabulary.yaml",
    "config/review_label_map.yaml",
]

OPTIONAL_LABEL_INPUTS = [
    "labels/candidate_label.nii.gz",
    "labels/draft_label.nii.gz",
    "labels/accepted_pseudo_label.nii.gz",
    "labels/verified_label.nii.gz",
]


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


def validate_manifest(root: Path, findings: list[Finding]) -> dict[str, Any] | None:
    manifest_path = root / "manifest.json"
    manifest, error = read_json(manifest_path)
    if error:
        findings.append(Finding("error", "manifest_invalid_json", f"manifest.json is invalid: {error}"))
        return None

    required_keys = [
        "package_id",
        "case_id",
        "created_at",
        "modality",
        "image",
        "label_policy",
        "review",
    ]
    for key in required_keys:
        if key not in manifest:
            findings.append(Finding("error", "manifest_missing_field", f"manifest.json missing required field: {key}"))

    image = manifest.get("image")
    if not isinstance(image, dict):
        findings.append(Finding("error", "manifest_image_type", "manifest.image must be an object"))
        return manifest

    primary_path = image.get("primary_path")
    dicom_path = image.get("dicom_path")
    if not primary_path and not dicom_path:
        findings.append(
            Finding(
                "error",
                "manifest_image_missing_path",
                "manifest.image must include primary_path or dicom_path",
            )
        )
    if primary_path and not (root / str(primary_path)).is_file():
        findings.append(Finding("error", "manifest_primary_missing", f"image.primary_path does not exist: {primary_path}"))
    if dicom_path and not (root / str(dicom_path)).exists():
        findings.append(Finding("warning", "manifest_dicom_missing", f"image.dicom_path does not exist: {dicom_path}"))

    if "shape" not in image:
        findings.append(Finding("error", "manifest_image_shape_missing", "manifest.image.shape is required"))
    if "spacing" not in image:
        findings.append(Finding("error", "manifest_image_spacing_missing", "manifest.image.spacing is required"))
    if "sha256" not in image:
        findings.append(Finding("warning", "manifest_image_sha_missing", "manifest.image.sha256 is missing"))

    if primary_path and image.get("sha256") and image.get("sha256") != "TO_BE_FILLED":
        actual_digest = sha256_file(root / str(primary_path))
        if actual_digest != image.get("sha256"):
            findings.append(
                Finding(
                    "error",
                    "manifest_primary_sha_mismatch",
                    f"image.primary_path sha256 mismatch: expected {image.get('sha256')}, got {actual_digest}",
                )
            )

    return manifest


def validate_required_files(root: Path, findings: list[Finding]) -> None:
    if not (root / "manifest.json").is_file():
        findings.append(Finding("error", "required_file_missing", "missing required file: manifest.json"))

    for rel_path in REQUIRED_CONFIG_FILES:
        if not (root / rel_path).is_file():
            findings.append(Finding("error", "required_file_missing", f"missing required file: {rel_path}"))


def validate_label_inputs(root: Path, findings: list[Finding]) -> None:
    has_known_label_file = any((root / rel_path).is_file() for rel_path in OPTIONAL_LABEL_INPUTS)
    has_mask_dir = any((root / "labels/masks").glob("*.nii*")) if (root / "labels/masks").is_dir() else False
    if not has_known_label_file and not has_mask_dir:
        findings.append(
            Finding(
                "warning",
                "label_input_missing",
                "no draft/accepted/verified label file or labels/masks/*.nii* found; package may be image-only",
            )
        )


def validate_checksums(root: Path, findings: list[Finding]) -> None:
    checksum_path = root / "checksums.sha256"
    if not checksum_path.is_file():
        findings.append(Finding("warning", "checksum_file_missing", "checksums.sha256 is missing"))
        return

    checksums, malformed = read_checksums(checksum_path)
    for line in malformed:
        findings.append(Finding("error", "checksum_malformed", f"malformed checksum entry: {line}"))

    for rel_path, expected_digest in checksums.items():
        path = root / rel_path
        if not path.is_file():
            findings.append(Finding("error", "checksum_file_missing", f"checksum references missing file: {rel_path}"))
            continue
        actual_digest = sha256_file(path)
        if actual_digest != expected_digest:
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
        "schema_version": "case_package_preflight/v0.1",
        "package_dir": str(root),
        "status": status,
        "case_id": manifest.get("case_id") if manifest else None,
        "package_id": manifest.get("package_id") if manifest else None,
        "findings": [item.__dict__ for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package_dir", type=Path)
    parser.add_argument("--json-output", type=Path, help="Optional path for preflight_report.json.")
    args = parser.parse_args()

    root = args.package_dir.resolve()
    if not root.is_dir():
        parser.error(f"package_dir is not a directory: {root}")

    findings: list[Finding] = []
    validate_required_files(root, findings)
    manifest = validate_manifest(root, findings) if (root / "manifest.json").is_file() else None
    validate_label_inputs(root, findings)
    validate_checksums(root, findings)
    report = build_report(root, findings, manifest)

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_output:
        args.json_output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
