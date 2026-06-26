from __future__ import annotations

import itertools
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from segplatform.adapters.mimics.doctor import load_workstation_config
from segplatform.common import load_data, prefixed_sha256, utc_now, write_json, write_yaml
from segplatform.errors import ConfigurationError, ValidationError
from segplatform.imaging import geometry_from_manifest


def _package_manifest(case_root: Path) -> dict[str, Any]:
    path = case_root.resolve() / "manifest.json"
    if not path.is_file():
        raise ValidationError(f"Case Package manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _probe_script(config: dict[str, Any]) -> Path:
    configured = config.get("probe_script_dir")
    if configured:
        root = Path(os.path.expandvars(str(configured))).expanduser()
    else:
        runtime = Path(os.path.expandvars(str(config["runtime_script_dir"]))).expanduser()
        root = runtime.parent / "probes"
    return root / "sp_probe_suite.py"


def build_probe_command(
    case_root: Path,
    workstation_config_path: Path,
    output_dir: Path | None = None,
) -> tuple[list[str], Path]:
    case_root = case_root.resolve()
    manifest = _package_manifest(case_root)
    dicom_images = [item for item in manifest["image_sets"] if item.get("dicom_path")]
    if not dicom_images:
        raise ConfigurationError("Mimics probe requires at least one DICOM image set in the Case Package")
    image = dicom_images[0]
    dicom_root = case_root / image["dicom_path"]
    config = load_workstation_config(workstation_config_path)
    executable = Path(os.path.expandvars(str(config["executable"]))).expanduser()
    script = _probe_script(config)
    selected_output = (output_dir or case_root / "reports" / "mimics_probe").resolve()
    if not executable.is_file():
        raise ConfigurationError(f"Mimics executable not found: {executable}")
    if not script.is_file():
        raise ConfigurationError(f"Mimics probe script not found: {script}")
    command = [
        str(executable),
        "-save_log",
        str(selected_output / "mimics_probe.log"),
        "-run_script",
        str(script),
        str(dicom_root.resolve()),
        str(selected_output),
    ]
    return command, selected_output


def run_probe(
    case_root: Path,
    workstation_config_path: Path,
    *,
    output_dir: Path | None = None,
    dry_run: bool = False,
    wait: bool = True,
) -> dict[str, Any]:
    command, selected_output = build_probe_command(case_root, workstation_config_path, output_dir)
    if dry_run:
        return {"command": command, "output_dir": str(selected_output), "started": False}
    selected_output.mkdir(parents=True, exist_ok=True)
    for name in (
        "mimics_probe_evidence.json",
        "mimics_probe_complete.json",
        "mimics_probe_error.json",
    ):
        stale = selected_output / name
        if stale.exists():
            stale.unlink()
    process = subprocess.Popen(command)
    result: dict[str, Any] = {
        "command": command,
        "output_dir": str(selected_output),
        "started": True,
        "pid": process.pid,
    }
    if wait:
        result["returncode"] = process.wait()
        result["evidence_path"] = str(selected_output / "mimics_probe_evidence.json")
    return result


def _platform_world(geometry: Any, index: np.ndarray) -> np.ndarray:
    direction = np.asarray(geometry.direction, dtype=float).reshape(3, 3)
    return np.asarray(geometry.origin, dtype=float) + direction @ (
        np.asarray(geometry.spacing, dtype=float) * index
    )


def _mimics_to_platform_index(
    mimics_index: np.ndarray,
    platform_shape: tuple[int, int, int],
    axes: tuple[int, int, int],
    flips: tuple[bool, bool, bool],
) -> np.ndarray:
    mimics_shape = tuple(platform_shape[axis] for axis in axes)
    transposed_index = mimics_index.astype(float).copy()
    for axis, should_flip in enumerate(flips):
        if should_flip:
            transposed_index[axis] = mimics_shape[axis] - 1 - transposed_index[axis]
    platform_index = np.zeros(3, dtype=float)
    for mimics_axis, platform_axis in enumerate(axes):
        platform_index[platform_axis] = transposed_index[mimics_axis]
    return platform_index


def solve_buffer_mapping(
    image_manifest: dict[str, Any],
    p05: dict[str, Any],
    *,
    tolerance_mm: float = 1e-3,
) -> dict[str, Any]:
    geometry = geometry_from_manifest(image_manifest)
    if geometry.coordinate_system != "LPS":
        raise ValidationError(
            f"automatic Mimics mapping evaluation currently requires LPS DICOM geometry, got {geometry.coordinate_system}"
        )
    observations = p05.get("voxel_centers", [])
    if len(observations) < 4:
        raise ValidationError("P05 evidence must contain the origin and three axis samples")
    detected_shape = tuple(int(value) for value in p05["logical_dimensions"])
    candidates = []
    for axes in itertools.permutations((0, 1, 2)):
        expected_shape = tuple(geometry.shape[axis] for axis in axes)
        if detected_shape != expected_shape:
            continue
        for flips in itertools.product((False, True), repeat=3):
            errors = []
            for observation in observations:
                mimics_index = np.asarray(observation["index"], dtype=float)
                platform_index = _mimics_to_platform_index(mimics_index, geometry.shape, axes, flips)
                predicted = _platform_world(geometry, platform_index)
                observed = np.asarray(observation["world"], dtype=float)
                errors.append(float(np.linalg.norm(predicted - observed)))
            candidates.append(
                {
                    "axes": list(axes),
                    "flips": list(flips),
                    "max_error_mm": max(errors),
                    "mean_error_mm": float(np.mean(errors)),
                }
            )
    if not candidates:
        raise ValidationError(
            f"P05 logical dimensions {detected_shape} cannot be mapped to platform shape {geometry.shape}"
        )
    candidates.sort(key=lambda item: (item["max_error_mm"], item["mean_error_mm"]))
    best = candidates[0]
    equally_good = [
        item for item in candidates if abs(item["max_error_mm"] - best["max_error_mm"]) <= tolerance_mm * 0.1
    ]
    passed = best["max_error_mm"] <= tolerance_mm and len(equally_good) == 1
    return {
        "status": "passed" if passed else "blocked",
        "tolerance_mm": tolerance_mm,
        "best": best,
        "candidate_count": len(candidates),
        "equally_good_candidate_count": len(equally_good),
    }


def evaluate_probe(
    case_root: Path,
    evidence_path: Path,
    workstation_config_path: Path,
    output_config_path: Path,
    *,
    tolerance_mm: float = 1e-3,
) -> dict[str, Any]:
    case_root = case_root.resolve()
    manifest = _package_manifest(case_root)
    evidence = load_data(evidence_path)
    if evidence.get("schema_version") != "mimics_probe_suite.v1":
        raise ValidationError("probe evidence schema_version must be mimics_probe_suite.v1")
    evidence_hash = prefixed_sha256(evidence_path)
    completion_path = evidence_path.resolve().parent / "mimics_probe_complete.json"
    if not completion_path.is_file():
        raise ValidationError(f"probe completion marker not found: {completion_path}")
    completion = load_data(completion_path)
    if (
        completion.get("schema_version") != "mimics_probe_complete.v1"
        or completion.get("status") != "passed"
        or completion.get("evidence_sha256") != evidence_hash
    ):
        raise ValidationError("probe completion marker does not match the evidence file")
    sections = evidence.get("sections", {})
    required = ("p01", "p02", "p04", "p05", "p06")
    missing = [name for name in required if name not in sections]
    if missing:
        raise ValidationError(f"probe evidence is missing sections: {missing}")

    p01_images = sections["p01"].get("image_sets", [])
    package_images = [item for item in manifest["image_sets"] if item.get("dicom_path")]
    if not package_images:
        raise ValidationError("Case Package has no DICOM image set for probe evaluation")
    expected = package_images[0]
    matching = [
        item
        for item in p01_images
        if item.get("dicom_series_uid_sha256") == expected.get("dicom_series_uid_sha256")
    ]
    if len(matching) != 1:
        raise ValidationError(
            f"probe evidence matched {len(matching)} image sets for {expected['image_id']}; expected exactly one"
        )

    section_statuses = {
        name: sections[name].get("status") in ("passed", "evidence_collected") for name in required
    }
    mapping_result = solve_buffer_mapping(expected, sections["p05"], tolerance_mm=tolerance_mm)
    passed = evidence.get("status") == "passed" and all(section_statuses.values()) and mapping_result["status"] == "passed"
    mapping = {
        "schema_version": "mimics_buffer_mapping.v1",
        "status": "verified" if passed else "unverified",
        "evidence_id": evidence_hash if passed else "",
        "platform_to_mimics_axes": mapping_result["best"]["axes"],
        "platform_to_mimics_flips": mapping_result["best"]["flips"],
    }
    config = load_workstation_config(workstation_config_path)
    config["buffer_mapping"] = mapping
    write_yaml(output_config_path, config)
    report = {
        "schema_version": "mimics_probe_evaluation.v1",
        "created_at": utc_now(),
        "case_root": str(case_root),
        "evidence_path": str(evidence_path.resolve()),
        "evidence_sha256": evidence_hash,
        "section_statuses": section_statuses,
        "mapping_evaluation": mapping_result,
        "generated_config": str(output_config_path.resolve()),
        "buffer_mapping": mapping,
        "status": "passed" if passed else "blocked",
    }
    report_path = evidence_path.resolve().parent / "mimics_probe_evaluation.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report
