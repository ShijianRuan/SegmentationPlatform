from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from segplatform.adapters.mimics.bridge import load_mapping, normalize_submission_entries, read_export_buffer
from segplatform.common import hash_directory, load_data, prefixed_sha256, utc_now, write_json
from segplatform.errors import ValidationError
from segplatform.imaging import geometry_from_manifest, write_mask_nifti
from segplatform.registry import FileRegistry
from segplatform.schema import validate_schema


def _report(case_root: Path, review_id: str, status: str, findings: list[dict[str, Any]]) -> Path:
    path = case_root / "reports" / "review_report.json"
    write_json(
        path,
        {
            "schema_version": "review_report.v1",
            "review_id": review_id,
            "created_at": utc_now(),
            "status": status,
            "findings": findings,
        },
    )
    return path


def _target_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {target["target_id"]: target for target in manifest["review"]["targets"]}


def _update_review(
    registry: FileRegistry,
    review_id: str,
    *,
    action: str,
    target_ids: list[str],
    label_ids: dict[str, str],
    actor: str | None,
) -> None:
    record = registry.get("reviews", review_id)
    status_by_action = {
        "submit_complete": "completed",
        "submit_for_review": "needs_review",
        "report_blocked": "blocked",
    }
    target_status = status_by_action[action]
    for target in record["targets"]:
        if target["target_id"] not in target_ids:
            continue
        target["status"] = target_status
        target["last_submission_at"] = utc_now()
        if target["target_id"] in label_ids:
            target["completed_label_id"] = label_ids[target["target_id"]]
    states = {target["status"] for target in record["targets"]}
    if states == {"completed"}:
        record["status"] = "completed"
    elif "needs_review" in states:
        record["status"] = "needs_review"
    elif "blocked" in states:
        record["status"] = "blocked"
    elif "in_progress" in states or "completed" in states:
        record["status"] = "in_progress"
    else:
        record["status"] = "ready"
    record.setdefault("events", []).append(
        {
            "at": utc_now(),
            "action": action,
            "actor": actor or "unknown",
            "target_ids": target_ids,
        }
    )
    registry.put("reviews", record, allow_update=True)


def _mark_qc_failed(
    registry: FileRegistry,
    review_id: str,
    target_ids: list[str],
    actor: str | None,
) -> None:
    record = registry.get("reviews", review_id)
    for target in record["targets"]:
        if target["target_id"] in target_ids:
            target["status"] = "in_progress"
            target["last_submission_at"] = utc_now()
    record["status"] = "in_progress"
    record.setdefault("events", []).append(
        {
            "at": utc_now(),
            "action": "qc_failed",
            "actor": actor or "unknown",
            "target_ids": target_ids,
        }
    )
    registry.put("reviews", record, allow_update=True)


def _submission_identity_findings(
    manifest: dict[str, Any],
    submission: dict[str, Any],
    target_ids: list[str],
    targets: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    findings = []
    expected_assignee = manifest["review"].get("assignee")
    if expected_assignee and submission.get("assignee") != expected_assignee:
        findings.append(
            {
                "severity": "error",
                "code": "assignee_mismatch",
                "message": f"submission assignee {submission.get('assignee')!r} != {expected_assignee!r}",
            }
        )
    submitted_bases = submission.get("base_labels", {})
    for target_id in target_ids:
        expected_id = targets[target_id].get("base_label_id")
        expected_hash = targets[target_id].get("base_label_sha256")
        submitted = submitted_bases.get(target_id)
        if expected_id:
            if not submitted or submitted.get("label_id") != expected_id or submitted.get("sha256") != expected_hash:
                findings.append(
                    {
                        "severity": "error",
                        "code": "base_label_mismatch",
                        "message": f"{target_id}: base label version does not match the assigned task",
                    }
                )
        elif submitted and (submitted.get("label_id") or submitted.get("sha256")):
            findings.append(
                {
                    "severity": "error",
                    "code": "unexpected_base_label",
                    "message": f"{target_id}: task has no base label but submission declares one",
                }
            )
    return findings


def finalize_case(
    case_root: Path,
    workstation_config_path: Path,
    registry_root: Path,
) -> dict[str, Any]:
    case_root = case_root.resolve()
    manifest = load_data(case_root / "manifest.json")
    review_id = manifest["review"]["review_id"]
    submission_root = case_root / "submissions" / review_id
    submission_path = submission_root / "submission_manifest.json"
    export_path = submission_root / "export_manifest.json"
    if not submission_path.is_file():
        raise ValidationError(f"Mimics submission intent not found: {submission_path}")
    submission = load_data(submission_path)
    if submission.get("schema_version") != "review_submission.v1" or submission.get("review_id") != review_id:
        raise ValidationError("submission manifest does not match the current review")
    action = submission.get("action")
    if action not in {"submit_complete", "submit_for_review", "report_blocked"}:
        raise ValidationError(f"unsupported submission action: {action}")
    target_ids = list(submission.get("target_ids", []))
    targets = _target_map(manifest)
    unknown_targets = set(target_ids) - set(targets)
    if not target_ids or unknown_targets:
        raise ValidationError(f"submission has invalid target_ids: {target_ids}")

    registry = FileRegistry(registry_root)
    identity_findings = _submission_identity_findings(manifest, submission, target_ids, targets)
    if identity_findings:
        _mark_qc_failed(registry, review_id, target_ids, submission.get("assignee"))
        _report(case_root, review_id, "failed", identity_findings)
        raise ValidationError("submission identity check failed; see reports/review_report.json")
    if action == "report_blocked":
        _update_review(
            registry,
            review_id,
            action=action,
            target_ids=target_ids,
            label_ids={},
            actor=submission.get("assignee"),
        )
        report_path = _report(
            case_root,
            review_id,
            "blocked",
            [{"severity": "error", "code": submission.get("reason_code", "annotator_blocked"), "message": submission.get("reason", "")}],
        )
        return {"status": "blocked", "report": str(report_path), "label_ids": []}

    if not export_path.is_file():
        raise ValidationError(f"Mimics export manifest not found: {export_path}")
    export_manifest = load_data(export_path)
    if (
        export_manifest.get("schema_version") != "mimics_export_manifest.v1"
        or export_manifest.get("review_id") != review_id
    ):
        raise ValidationError("export manifest schema_version must be mimics_export_manifest.v1")
    entries = list(export_manifest.get("entries", []))
    normalize_submission_entries(entries)
    entry_map = {(entry["target_id"], entry["organ"]): entry for entry in entries}
    outcomes = submission.get("organ_outcomes", {})
    findings = []
    for target_id in target_ids:
        target = targets[target_id]
        for organ in target["organs"]:
            outcome = outcomes.get(target_id, {}).get(organ, "present")
            if (target_id, organ) not in entry_map:
                findings.append(
                    {"severity": "error", "code": "missing_mask", "message": f"{target_id}/{organ}: exported Mask is missing"}
                )
            if action == "submit_complete" and outcome == "uncertain":
                findings.append(
                    {"severity": "error", "code": "uncertain_complete", "message": f"{target_id}/{organ}: uncertain cannot be completed"}
                )
            if outcome not in {"present", "confirmed_absent", "uncertain"}:
                findings.append(
                    {
                        "severity": "error",
                        "code": "invalid_organ_outcome",
                        "message": f"{target_id}/{organ}: invalid outcome {outcome}",
                    }
                )
            entry = entry_map.get((target_id, organ))
            if entry and entry.get("image_id") != target["image_id"]:
                findings.append(
                    {
                        "severity": "error",
                        "code": "image_id_mismatch",
                        "message": f"{target_id}/{organ}: exported image_id does not match the target",
                    }
                )
    if findings:
        _mark_qc_failed(registry, review_id, target_ids, submission.get("assignee"))
        _report(case_root, review_id, "failed", findings)
        raise ValidationError("submission QC failed:\n- " + "\n- ".join(item["message"] for item in findings))

    config = load_data(workstation_config_path)
    mapping_path = config.get("buffer_mapping_file")
    if mapping_path:
        mapping = load_mapping(Path(mapping_path).expanduser())
    else:
        from segplatform.imaging import BufferMapping

        mapping = BufferMapping.from_config(config["buffer_mapping"])
    prepared_targets = []
    for target_id in target_ids:
        target = targets[target_id]
        image = next(item for item in manifest["image_sets"] if item["image_id"] == target["image_id"])
        geometry = geometry_from_manifest(image)
        prepared_segments = []
        for organ in target["organs"]:
            entry = entry_map[(target_id, organ)]
            array = read_export_buffer(entry, mapping, case_root=case_root)
            outcome = outcomes.get(target_id, {}).get(organ, "present")
            if outcome == "confirmed_absent":
                array[:] = False
            elif not array.any():
                findings.append(
                    {
                        "severity": "error" if action == "submit_complete" else "warning",
                        "code": "empty_mask",
                        "message": f"{target_id}/{organ}: empty Mask without confirmed_absent",
                    }
                )
            prepared_segments.append({"organ": organ, "array": array})
        prepared_targets.append(
            {
                "target_id": target_id,
                "target": target,
                "geometry": geometry,
                "segments": prepared_segments,
            }
        )
    if any(item["severity"] == "error" for item in findings):
        _mark_qc_failed(registry, review_id, target_ids, submission.get("assignee"))
        _report(case_root, review_id, "failed", findings)
        raise ValidationError("submission QC failed; see reports/review_report.json")

    label_ids: dict[str, str] = {}
    created_records = []
    for prepared in prepared_targets:
        target_id = prepared["target_id"]
        target = prepared["target"]
        geometry = prepared["geometry"]
        output_root = submission_root / "labels" / target["image_id"] / target_id
        output_root.mkdir(parents=True, exist_ok=True)
        segments = []
        generators_by_organ: dict[str, list[str]] = {}
        usage_constraints = {
            "model_training": "needs_policy",
            "commercial_use": "needs_policy",
            "redistribution": "needs_policy",
        }
        if target.get("base_label_id"):
            base_record = registry.get("labels", target["base_label_id"])
            usage_constraints = base_record.get("usage_constraints", usage_constraints)
            for base_segment in base_record["segments"]:
                if base_segment["organ"] in target["organs"]:
                    generators_by_organ[base_segment["organ"]] = list(
                        base_segment["lineage"]["contributing_generators"]
                    )
        for prepared_segment in prepared["segments"]:
            organ = prepared_segment["organ"]
            destination = output_root / f"{organ}.nii.gz"
            write_mask_nifti(destination, prepared_segment["array"], geometry)
            segments.append(
                {
                    "organ": organ,
                    "path": str(destination.resolve()),
                    "lifecycle_status": "verified_label" if action == "submit_complete" else "draft_label",
                    "source": {"type": "manual_review", "review_id": review_id},
                    "lineage": {
                        "derived_from_label_ids": [target["base_label_id"]] if target.get("base_label_id") else [],
                        "contributing_generators": sorted(set(generators_by_organ.get(organ, []))),
                    },
                }
            )
        label_id = f"label_{target['image_id']}_{uuid.uuid4().hex[:12]}"
        label_record = {
            "schema_version": "label_artifact.v1",
            "label_id": label_id,
            "case_id": manifest["case_id"],
            "image_id": target["image_id"],
            "path": str(output_root.resolve()),
            "format": "per_organ_masks",
            "hash": hash_directory(output_root),
            "hash_scope": "bundle_manifest",
            "pixel_type": "uint8",
            "geometry_ref": target["image_id"],
            "geometry": {
                "shape": list(geometry.shape),
                "spacing": list(geometry.spacing),
                "origin": list(geometry.origin),
                "direction": list(geometry.direction),
                "geometry_status": "complete",
                "geometry_evidence": {
                    "shape": "sidecar",
                    "spacing": "sidecar",
                    "origin": "sidecar",
                    "direction": "sidecar",
                    "assumptions": [
                        f"Mimics buffer mapping verified by {mapping.evidence_id}",
                    ],
                },
                "alignment_checked": True,
                "alignment_basis": "physical_space",
            },
            "artifact_lifecycle": "active",
            "usage_constraints": usage_constraints,
            "parent_label_id": target.get("base_label_id"),
            "segments": segments,
        }
        validate_schema(label_record, "label_artifact.schema.json")
        registry.put("labels", label_record)
        label_ids[target_id] = label_id
        created_records.append(label_record)

    _update_review(
        registry,
        review_id,
        action=action,
        target_ids=target_ids,
        label_ids=label_ids,
        actor=submission.get("assignee"),
    )
    report_status = "passed" if action == "submit_complete" else "needs_review"
    report_path = _report(case_root, review_id, report_status, findings)
    write_json(
        case_root / "provenance" / "tool_export.json",
        {
            "schema_version": "tool_export.v1",
            "review_id": review_id,
            "tool": "Mimics Research",
            "tool_version": export_manifest.get("mimics_version"),
            "runtime": export_manifest.get("python_version"),
            "buffer_mapping_evidence_id": mapping.evidence_id,
            "submission_manifest_sha256": prefixed_sha256(submission_path),
            "export_manifest_sha256": prefixed_sha256(export_path),
            "created_at": utc_now(),
        },
    )
    return {
        "status": report_status,
        "report": str(report_path),
        "label_ids": list(label_ids.values()),
        "records": created_records,
    }
