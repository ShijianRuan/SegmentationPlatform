# -*- coding: utf-8 -*-
"""Export selected review targets and write a submission intent for platform QC."""

from __future__ import print_function

import os
import sys

import mimics

from sp_common import (
    expected_mimics_shape,
    export_mask_u8,
    find_mask,
    load_json,
    managed_masks,
    match_images,
    metadata_get,
    TOGGLE_PREFIX_CLEAR,
    TOGGLE_PREFIX_SELECTED,
    write_error_report,
    write_json,
)


def discover_runtime():
    masks = managed_masks(mimics)
    if not masks:
        raise RuntimeError("No SegmentationPlatform managed Masks were found")
    review_ids = set(metadata_get(mask, "sp.review_id", "") for mask in masks)
    package_roots = set(metadata_get(mask, "sp.package_root", "") for mask in masks)
    if len(review_ids) != 1 or "" in review_ids:
        raise RuntimeError("The project contains zero or multiple review_id values")
    if len(package_roots) != 1 or "" in package_roots:
        raise RuntimeError("The project contains zero or multiple package roots")
    package_root = list(package_roots)[0]
    runtime_path = os.path.join(package_root, "working", "mimics_runtime.json")
    return load_json(runtime_path)


def choose_action():
    answer = mimics.dialogs.question_box(
        message="Choose what to do with the current review.",
        buttons="Submit Complete;Submit For Review;Report Blocked;Cancel",
        title="SP - Submit Review",
        ui_blocking=True,
    )
    return {
        "Submit Complete": "submit_complete",
        "Submit For Review": "submit_for_review",
        "Report Blocked": "report_blocked",
        "Cancel": "cancel",
    }.get(answer, "cancel")


def choose_targets(runtime):
    target_ids = [target["target_id"] for target in runtime["targets"]]
    if len(target_ids) == 1:
        return target_ids
    if 2 <= len(target_ids) <= 5:
        selected = []
        while True:
            toggle_buttons = [
                (TOGGLE_PREFIX_SELECTED if target_id in selected else TOGGLE_PREFIX_CLEAR) + str(index + 1)
                for index, target_id in enumerate(target_ids)
            ]
            buttons = toggle_buttons + ["Use Selected", "All Targets", "Cancel"]
            answer = mimics.dialogs.question_box(
                message="Toggle target groups, then choose Use Selected.\n\n{0}\n\nSelected: {1}".format(
                    "\n".join(
                        "{0}. {1}".format(index + 1, target_id)
                        for index, target_id in enumerate(target_ids)
                    ),
                    ", ".join(selected) if selected else "none",
                ),
                buttons=";".join(buttons),
                title="SP - Target Groups",
                ui_blocking=True,
            )
            if answer == "All Targets":
                return target_ids
            if answer == "Cancel":
                return []
            if answer == "Use Selected":
                if selected:
                    return selected
                mimics.dialogs.message_box(
                    "No target group is selected.",
                    title="SP - Target Groups",
                    ui_blocking=True,
                )
                continue
            for index, target_id in enumerate(target_ids):
                if answer in (TOGGLE_PREFIX_CLEAR + str(index + 1), TOGGLE_PREFIX_SELECTED + str(index + 1)):
                    if target_id in selected:
                        selected.remove(target_id)
                    else:
                        selected.append(target_id)
                    break
            else:
                mimics.dialogs.message_box(
                    "The target selection response was not recognized. Please choose again.",
                    title="SP - Target Groups",
                    ui_blocking=True,
                )
        return []
    buttons = ["All Targets"] + target_ids + ["Cancel"]
    answer = mimics.dialogs.question_box(
        message="Choose the target group to submit.",
        buttons=";".join(buttons),
        title="SP - Target Group",
        ui_blocking=True,
    )
    if answer == "All Targets":
        return target_ids
    if answer == "Cancel" or answer not in target_ids:
        return []
    return [answer]


def choose_reason(action):
    if action == "submit_for_review":
        buttons = "Medical Uncertainty;Image Quality;Missing Context;Other;Cancel"
    else:
        buttons = "Data Missing;Wrong Image Set;Tool Error;Script Error;Other;Cancel"
    answer = mimics.dialogs.question_box(
        message="Choose the main reason.",
        buttons=buttons,
        title="SP - Reason",
        ui_blocking=True,
    )
    if answer == "Cancel":
        return None
    return answer.lower().replace(" ", "_")


def preflight_targets(runtime, selected_targets):
    findings = []
    empty_masks = []
    try:
        image_map = match_images(mimics, runtime["image_sets"])
    except Exception as error:
        return [{"message": "Image set matching failed: {0}".format(str(error))}], []
    for target in selected_targets:
        expected_image = image_map[target["image_id"]]
        expected_shape = expected_mimics_shape(runtime, target["image_id"])
        for expected in target["masks"]:
            organ = expected["organ"]
            label = "{0}/{1}".format(target["target_id"], organ)
            mask = find_mask(mimics, runtime["review_id"], target["target_id"], organ)
            if mask is None:
                findings.append({"message": "{0}: Mask is missing".format(label)})
                continue
            if mask.image != expected_image:
                findings.append({"message": "{0}: Mask is linked to the wrong image set".format(label)})
            metadata_checks = {
                "sp.image_id": target["image_id"],
                "sp.base_label_id": target.get("base_label_id", ""),
                "sp.base_label_hash": target.get("base_label_sha256", ""),
            }
            for key, expected_value in metadata_checks.items():
                actual = metadata_get(mask, key, "")
                if actual != expected_value:
                    findings.append(
                        {
                            "message": "{0}: {1} is {2!r}, expected {3!r}".format(
                                label, key, actual, expected_value
                            )
                        }
                    )
            try:
                actual_shape = [int(value) for value in mask.get_voxel_buffer().shape]
                if actual_shape != expected_shape:
                    findings.append(
                        {
                            "message": "{0}: Mask shape {1} does not match expected {2}".format(
                                label, actual_shape, expected_shape
                            )
                        }
                    )
                if int(mask.number_of_pixels) == 0:
                    empty_masks.append((target["target_id"], organ))
            except Exception as error:
                findings.append({"message": "{0}: cannot read Mask buffer: {1}".format(label, str(error))})
    return findings, empty_masks


def show_preflight_failure(runtime, findings):
    report_path = os.path.join(runtime["reports_dir"], "mimics_submit_precheck.json")
    write_json(
        report_path,
        {
            "schema_version": "mimics_submit_precheck.v1",
            "review_id": runtime["review_id"],
            "status": "failed",
            "findings": findings,
        },
    )
    lines = ["- " + finding["message"] for finding in findings[:8]]
    if len(findings) > 8:
        lines.append("- ... and {0} more".format(len(findings) - 8))
    mimics.dialogs.message_box(
        "Submission is blocked:\n{0}\n\nReport:\n{1}".format("\n".join(lines), report_path),
        title="SP - Submission Precheck Failed",
        ui_blocking=True,
    )


def resolve_empty_masks(empty_masks):
    if not empty_masks:
        return {}, False
    labels = ["{0}/{1}".format(target_id, organ) for target_id, organ in empty_masks]
    answer = mimics.dialogs.question_box(
        message="The following Masks are empty:\n- {0}\n\nChoose one outcome for all, or review them individually.".format(
            "\n- ".join(labels)
        ),
        buttons="All Confirmed Absent;All Need Review;Review One By One;Cancel",
        title="SP - Empty Masks",
        ui_blocking=True,
    )
    if answer == "Cancel":
        return None, False
    if answer == "All Confirmed Absent":
        return dict(((target_id, organ), "confirmed_absent") for target_id, organ in empty_masks), False
    if answer == "All Need Review":
        return dict(((target_id, organ), "uncertain") for target_id, organ in empty_masks), True

    outcomes = {}
    needs_review = False
    for target_id, organ in empty_masks:
        item_answer = mimics.dialogs.question_box(
            message="{0}/{1} is empty. Confirm why.".format(target_id, organ),
            buttons="Confirmed Absent;Needs Review;Cancel",
            title="SP - Empty Mask",
            ui_blocking=True,
        )
        if item_answer == "Confirmed Absent":
            outcomes[(target_id, organ)] = "confirmed_absent"
        elif item_answer == "Needs Review":
            outcomes[(target_id, organ)] = "uncertain"
            needs_review = True
        else:
            return None, False
    return outcomes, needs_review


def main():
    runtime = discover_runtime()
    action = choose_action()
    if action == "cancel":
        return 0
    target_ids = choose_targets(runtime)
    if not target_ids:
        return 0
    reason_code = choose_reason(action) if action in ("submit_for_review", "report_blocked") else None
    if action in ("submit_for_review", "report_blocked") and reason_code is None:
        return 0

    submission_root = runtime["submissions_dir"]
    if not os.path.isdir(submission_root):
        os.makedirs(submission_root)
    selected_targets = [target for target in runtime["targets"] if target["target_id"] in target_ids]
    base_labels = {}
    entries = []
    organ_outcomes = {}

    if action != "report_blocked":
        findings, empty_masks = preflight_targets(runtime, selected_targets)
        if findings:
            show_preflight_failure(runtime, findings)
            return 2
        empty_outcomes, empty_needs_review = resolve_empty_masks(empty_masks)
        if empty_outcomes is None:
            return 0
        if empty_needs_review:
            if action == "submit_complete":
                confirm = mimics.dialogs.question_box(
                    message=(
                        "At least one empty Mask was marked as needing review.\n\n"
                        "This cannot be submitted as Complete. The submission will be changed to Submit For Review."
                    ),
                    buttons="Submit For Review;Cancel",
                    title="SP - Submit Type Changed",
                    ui_blocking=True,
                )
                if confirm != "Submit For Review":
                    return 0
            action = "submit_for_review"
            if reason_code is None:
                reason_code = "medical_uncertainty"
        for target in selected_targets:
            if target.get("base_label_id"):
                base_labels[target["target_id"]] = {
                    "label_id": target.get("base_label_id"),
                    "sha256": target.get("base_label_sha256"),
                }
            organ_outcomes[target["target_id"]] = {}
            for expected in target["masks"]:
                organ = expected["organ"]
                mask = find_mask(mimics, runtime["review_id"], target["target_id"], organ)
                if mask is None:
                    raise RuntimeError("Missing Mask: {0}/{1}".format(target["target_id"], organ))
                if metadata_get(mask, "sp.image_id") != target["image_id"]:
                    raise RuntimeError("Mask metadata image_id mismatch: {0}/{1}".format(target["target_id"], organ))
                outcome = empty_outcomes.get((target["target_id"], organ), "present")
                organ_outcomes[target["target_id"]][organ] = outcome
                output_path = os.path.join(
                    submission_root, "buffers", target["image_id"], target["target_id"], organ + ".u8"
                )
                exported = export_mask_u8(mask, output_path)
                exported["path"] = os.path.relpath(output_path, runtime["package_root"]).replace("\\", "/")
                exported["path_base"] = "package_root"
                exported.update(
                    {
                        "target_id": target["target_id"],
                        "image_id": target["image_id"],
                        "organ": organ,
                        "platform_shape": next(
                            image["platform_shape"]
                            for image in runtime["image_sets"]
                            if image["image_id"] == target["image_id"]
                        ),
                    }
                )
                entries.append(exported)

        write_json(
            os.path.join(submission_root, "export_manifest.json"),
            {
                "schema_version": "mimics_export_manifest.v1",
                "review_id": runtime["review_id"],
                "mimics_version": str(mimics.get_version()),
                "python_version": sys.version,
                "entries": entries,
            },
        )

    submission = {
        "schema_version": "review_submission.v1",
        "review_id": runtime["review_id"],
        "target_ids": target_ids,
        "action": action,
        "assignee": runtime.get("assignee"),
        "base_labels": base_labels,
        "organ_outcomes": organ_outcomes,
        "reason_code": reason_code,
    }
    write_json(os.path.join(submission_root, "submission_manifest.json"), submission)
    mimics.file.save_project(filename=runtime["mcs_path"], save_as_type="Mimics Project Files")
    mimics.dialogs.message_box(
        "The review was exported. Platform QC is still required before any label is verified.\n\n"
        "If Finalize fails, read reports/review_report.json. The next Open also shows the latest QC failure.",
        title="SP - Export Complete",
        ui_blocking=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        try:
            runtime_value = discover_runtime()
            error_path = os.path.join(runtime_value["reports_dir"], "mimics_submit_error.json")
        except Exception:
            error_path = os.path.abspath("mimics_submit_error.json")
        write_error_report(error_path, "submit_review", error)
        try:
            mimics.dialogs.message_box(
                "The review could not be exported. See mimics_submit_error.json.\n\n{0}".format(str(error)),
                title="SegmentationPlatform - Export Failed",
                ui_blocking=True,
            )
        finally:
            raise
