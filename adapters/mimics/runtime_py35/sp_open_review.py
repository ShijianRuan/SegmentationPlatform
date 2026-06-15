# -*- coding: utf-8 -*-
"""Open or create one review workspace in Mimics Research 21."""

from __future__ import print_function

import os
import sys

import mimics

from sp_common import (
    apply_predefined_answers,
    find_mask,
    load_json,
    match_images,
    metadata_get,
    metadata_set,
    sha256_file,
    set_mask_buffer_from_u8,
    write_error_report,
    write_json,
)


def import_entry_map(runtime):
    result = {}
    for entry in runtime.get("import_buffers", []):
        result[(entry["image_id"], entry["organ"])] = entry
    return result


def checkpoint_entry_map(runtime):
    result = {}
    for entry in runtime.get("checkpoint_buffers", []):
        result[(entry["image_id"], entry["target_id"], entry["organ"])] = entry
    return result


def validate_existing_mask(mask, target, organ):
    expected = {
        "sp.image_id": target["image_id"],
        "sp.base_label_id": target.get("base_label_id", ""),
        "sp.base_label_hash": target.get("base_label_sha256", ""),
    }
    mismatches = []
    for key, expected_value in expected.items():
        actual = metadata_get(mask, key, "")
        if actual != expected_value:
            mismatches.append("{0}: stored={1!r}, expected={2!r}".format(key, actual, expected_value))
    if mismatches:
        raise RuntimeError(
            "Existing Mask is based on a different task version: {0}/{1}. {2}".format(
                target["target_id"], organ, "; ".join(mismatches)
            )
        )


def previous_qc_summary(runtime):
    report_path = os.path.join(runtime["reports_dir"], "review_report.json")
    if not os.path.isfile(report_path):
        return ""
    report = load_json(report_path)
    if report.get("status") != "failed":
        return ""
    findings = report.get("findings", [])
    lines = []
    for finding in findings[:5]:
        lines.append("- {0}".format(finding.get("message") or finding.get("code") or "Unknown QC error"))
    if len(findings) > 5:
        lines.append("- ... and {0} more".format(len(findings) - 5))
    return "Previous platform QC failed:\n{0}\nReport: {1}".format("\n".join(lines), report_path)


def main():
    if len(sys.argv) < 2:
        raise RuntimeError("usage: sp_open_review.py MIMICS_RUNTIME_JSON")
    runtime_path = os.path.abspath(sys.argv[1])
    runtime = load_json(runtime_path)
    reports_dir = runtime["reports_dir"]
    if not os.path.isdir(reports_dir):
        os.makedirs(reports_dir)

    apply_predefined_answers(mimics, runtime.get("predefined_dialog_answers", {}))
    if runtime["mode"] == "resume" and os.path.isfile(runtime["mcs_path"]):
        mimics.file.open_project(filename=runtime["mcs_path"])
    else:
        mimics.file.import_dicom_images(source_folder=runtime["dicom_import_root"])

    image_map = match_images(mimics, runtime["image_sets"])
    imports = import_entry_map(runtime)
    checkpoints = checkpoint_entry_map(runtime)
    mask_records = []
    warnings = []
    for target in runtime["targets"]:
        image = image_map[target["image_id"]]
        mimics.data.images.set_active(image)
        for expected_mask in target["masks"]:
            organ = expected_mask["organ"]
            mask = find_mask(mimics, runtime["review_id"], target["target_id"], organ)
            created = mask is None
            binding_error = None
            if created:
                mask = mimics.segment.create_mask()
                mask.name = expected_mask["name"]
                try:
                    mask.image = image
                except Exception as error:
                    binding_error = "{0}: {1}".format(error.__class__.__name__, str(error))
            else:
                validate_existing_mask(mask, target, organ)
            if mask.image != image:
                raise RuntimeError(
                    "Mask is linked to the wrong image set: {0}/{1}. Binding error: {2}".format(
                        target["target_id"], organ, binding_error or "none"
                    )
                )
            if binding_error:
                warnings.append(
                    "{0}/{1}: assigning mask.image raised {2}, but the active image binding is correct".format(
                        target["target_id"], organ, binding_error
                    )
                )
            metadata_set(mask, "sp.review_id", runtime["review_id"])
            metadata_set(mask, "sp.target_id", target["target_id"])
            metadata_set(mask, "sp.image_id", target["image_id"])
            metadata_set(mask, "sp.organ", organ)
            if created:
                metadata_set(mask, "sp.base_label_id", target.get("base_label_id", ""))
                metadata_set(mask, "sp.base_label_hash", target.get("base_label_sha256", ""))
            metadata_set(mask, "sp.package_root", runtime["package_root"])
            import_entry = imports.get((target["image_id"], organ))
            checkpoint_entry = checkpoints.get((target["image_id"], target["target_id"], organ))
            import_method = None
            if created and checkpoint_entry is not None:
                if sha256_file(checkpoint_entry["path"]) != checkpoint_entry["sha256"]:
                    raise RuntimeError("Checkpoint hash mismatch: {0}/{1}".format(target["target_id"], organ))
                import_method = "checkpoint_" + set_mask_buffer_from_u8(
                    mask, checkpoint_entry["path"], checkpoint_entry["mimics_shape"]
                )
            elif created and import_entry is not None:
                import_method = set_mask_buffer_from_u8(mask, import_entry["path"], import_entry["mimics_shape"])
            mask_records.append(
                {
                    "target_id": target["target_id"],
                    "image_id": target["image_id"],
                    "organ": organ,
                    "mask_name": mask.name,
                    "created": created,
                    "import_method": import_method,
                    "binding_warning": binding_error,
                }
            )

    mimics.file.save_project(filename=runtime["mcs_path"], save_as_type="Mimics Project Files")
    report = {
        "schema_version": "mimics_open_report.v1",
        "review_id": runtime["review_id"],
        "mimics_version": str(mimics.get_version()),
        "image_sets": [
            {"image_id": image_id, "logical_dimensions": [int(value) for value in image.logical_dimensions]}
            for image_id, image in image_map.items()
        ],
        "masks": mask_records,
        "warnings": warnings,
        "status": "passed_with_warnings" if warnings else "passed",
    }
    write_json(os.path.join(reports_dir, "mimics_open_report.json"), report)
    summary = "Review: {0}\nCase: {1}\nTargets: {2}\nMasks: {3}".format(
        runtime["review_id"], runtime["case_id"], len(runtime["targets"]), len(mask_records)
    )
    qc_summary = previous_qc_summary(runtime)
    if qc_summary:
        summary = summary + "\n\n" + qc_summary
    mimics.dialogs.message_box(summary, title="SegmentationPlatform Review", ui_blocking=True)
    return 0


if __name__ == "__main__":
    runtime_json = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else ""
    try:
        sys.exit(main())
    except Exception as error:
        report_path = os.path.join(os.path.dirname(runtime_json), "..", "reports", "mimics_open_error.json")
        write_error_report(os.path.abspath(report_path), "open_review", error)
        try:
            mimics.dialogs.message_box(
                "The review could not be opened. See mimics_open_error.json.\n\n{0}".format(str(error)),
                title="SegmentationPlatform - Blocked",
                ui_blocking=True,
            )
        finally:
            raise
