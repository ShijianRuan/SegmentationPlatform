# -*- coding: utf-8 -*-
"""Export selected review targets and write a submission intent for platform QC."""

from __future__ import print_function

import os
import shutil
import sys
import time
import uuid

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

SUBMIT_TITLE = "Submit Labeling Result"
BUTTON_COMPLETE = "Complete"
BUTTON_REVIEW = "Needs Review"
BUTTON_PROBLEM = "Report Problem"
BUTTON_CANCEL = "Cancel"
ACTION_BY_BUTTON = {
    BUTTON_COMPLETE: "submit_complete",
    BUTTON_REVIEW: "submit_for_review",
    BUTTON_PROBLEM: "report_blocked",
    BUTTON_CANCEL: "cancel",
}


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
ALLOWED_ACTIONS = set(["submit_complete", "submit_for_review", "report_blocked", "cancel"])

BUTTON_USE_SELECTED = "Use Selected"
BUTTON_ALL_GROUPS = "All Groups"

EMPTY_PREVIEW_LIMIT = 30
BUTTON_ALL_ABSENT = "All Confirmed Absent"
BUTTON_ALL_REVIEW = "All Need Review"
BUTTON_REVIEW_ONE_BY_ONE = "Review One By One"
BUTTON_CONTINUE_EXPORT = "Continue Export"
UNMANAGED_PREVIEW_LIMIT = 20


def cleanup_staging(submission_root):
    parent = os.path.dirname(submission_root)
    base = os.path.basename(submission_root)
    if not os.path.isdir(parent):
        return
    previous = os.path.join(parent, base + ".previous")
    if (not os.path.exists(submission_root)) and os.path.isdir(previous):
        os.rename(previous, submission_root)
    for name in os.listdir(parent):
        path = os.path.join(parent, name)
        if name.startswith(base + ".partial_") and os.path.isdir(path):
            shutil.rmtree(path)


def publish_staged_submission(staging_root, submission_root):
    parent = os.path.dirname(submission_root)
    base = os.path.basename(submission_root)
    previous = os.path.join(parent, base + ".previous")
    if os.path.isdir(previous):
        shutil.rmtree(previous)
    if os.path.isdir(submission_root):
        os.rename(submission_root, previous)
    os.rename(staging_root, submission_root)
    if os.path.isdir(previous):
        shutil.rmtree(previous)


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
        message="Choose the result for the current work.",
        buttons=";".join([BUTTON_COMPLETE, BUTTON_REVIEW, BUTTON_PROBLEM, BUTTON_CANCEL]),
        title=SUBMIT_TITLE,
        ui_blocking=True,
    )
    return ACTION_BY_BUTTON.get(answer, "cancel")


def normalize_action(action_override=None):
    if action_override is None:
        return choose_action()
    if action_override not in ALLOWED_ACTIONS:
        raise RuntimeError("Unsupported submit action: {0}".format(action_override))
    return action_override


def target_display(target):
    organs = [item.get("organ", "") for item in target.get("masks", [])]
    preview = ", ".join(organs[:4])
    if len(organs) > 4:
        preview = preview + ", ..."
    return "{0}: {1} organ(s) on image {2}{3}".format(
        target.get("target_id", ""),
        len(organs),
        target.get("image_id", ""),
        " ({0})".format(preview) if preview else "",
    )


def choose_targets(runtime):
    target_ids = [target["target_id"] for target in runtime["targets"]]
    target_map = dict((target["target_id"], target) for target in runtime["targets"])
    if len(target_ids) == 1:
        return target_ids
    if 2 <= len(target_ids) <= 5:
        selected = []
        while True:
            toggle_buttons = [
                (TOGGLE_PREFIX_SELECTED if target_id in selected else TOGGLE_PREFIX_CLEAR) + str(index + 1)
                for index, target_id in enumerate(target_ids)
            ]
            buttons = toggle_buttons + [BUTTON_USE_SELECTED, BUTTON_ALL_GROUPS, BUTTON_CANCEL]
            answer = mimics.dialogs.question_box(
                message="Toggle image/organ groups, then choose Use Selected.\n\n{0}\n\nSelected: {1}".format(
                    "\n".join(
                        "{0}. {1}".format(index + 1, target_display(target_map[target_id]))
                        for index, target_id in enumerate(target_ids)
                    ),
                    ", ".join(selected) if selected else "none",
                ),
                buttons=";".join(buttons),
                title="Image/Organ Groups",
                ui_blocking=True,
            )
            if answer == BUTTON_ALL_GROUPS:
                return target_ids
            if answer == BUTTON_CANCEL:
                return []
            if answer == BUTTON_USE_SELECTED:
                if selected:
                    return selected
                mimics.dialogs.message_box(
                    "No image/organ group is selected.",
                    title="Image/Organ Groups",
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
                    title="Image/Organ Groups",
                    ui_blocking=True,
                )
        return []
    buttons = [BUTTON_ALL_GROUPS] + target_ids + [BUTTON_CANCEL]
    answer = mimics.dialogs.question_box(
        message="Choose the image/organ group to submit.",
        buttons=";".join(buttons),
        title="Image/Organ Group",
        ui_blocking=True,
    )
    if answer == BUTTON_ALL_GROUPS:
        return target_ids
    if answer == BUTTON_CANCEL or answer not in target_ids:
        return []
    return [answer]


def choose_reason(action):
    if action == "submit_for_review":
        buttons = "Uncertain Anatomy;Image Quality;Need More Context;Other;Cancel"
    else:
        buttons = "Missing Data;Wrong Image;Tool Error;Script Error;Other;Cancel"
    answer = mimics.dialogs.question_box(
        message="Choose the main reason.",
        buttons=buttons,
        title="Reason",
        ui_blocking=True,
    )
    if answer == BUTTON_CANCEL:
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


def write_text(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(text)
        handle.write("\n")


def unmanaged_mask_names():
    names = []
    for mask in mimics.data.masks:
        if not metadata_get(mask, "sp.review_id", ""):
            names.append(getattr(mask, "name", "") or "<unnamed>")
    return names


def confirm_unmanaged_masks_ignored(runtime):
    names = unmanaged_mask_names()
    if not names:
        return True
    report_path = os.path.join(runtime["reports_dir"], "mimics_unmanaged_masks.txt")
    write_text(report_path, "Unmanaged Masks:\n- " + "\n- ".join(names))
    preview = names[:UNMANAGED_PREVIEW_LIMIT]
    lines = [
        "This Mimics project contains {0} Mask(s) that are not part of this platform task.".format(len(names)),
        "",
        "- " + "\n- ".join(preview),
    ]
    if len(names) > UNMANAGED_PREVIEW_LIMIT:
        lines.append("")
        lines.append("Only the first {0} are shown here.".format(UNMANAGED_PREVIEW_LIMIT))
    lines.extend(
        [
            "",
            "These Mask(s) will NOT be exported or verified by this submission.",
            "If one of them should become official, cancel and ask the platform operator for a follow-up task.",
            "",
            "Full list: {0}".format(report_path),
        ]
    )
    answer = mimics.dialogs.question_box(
        message="\n".join(lines),
        buttons=BUTTON_CONTINUE_EXPORT + ";" + BUTTON_CANCEL,
        title="Unmanaged Masks",
        ui_blocking=True,
    )
    return answer == BUTTON_CONTINUE_EXPORT


def empty_mask_preview(empty_masks, runtime=None):
    labels = ["{0}/{1}".format(target_id, organ) for target_id, organ in empty_masks]
    full_text = "Empty Masks:\n- " + "\n- ".join(labels)
    report_path = None
    if runtime is not None:
        report_path = os.path.join(runtime["reports_dir"], "mimics_empty_masks.txt")
        write_text(report_path, full_text)
    preview = labels[:EMPTY_PREVIEW_LIMIT]
    lines = [
        "{0} Mask(s) are empty.".format(len(labels)),
        "",
        "- " + "\n- ".join(preview),
    ]
    if len(labels) > EMPTY_PREVIEW_LIMIT:
        lines.append("")
        lines.append("Only the first {0} are shown here.".format(EMPTY_PREVIEW_LIMIT))
        if report_path:
            lines.append("Full list: {0}".format(report_path))
    return "\n".join(lines)


def resolve_empty_masks(empty_masks, runtime=None):
    if not empty_masks:
        return {}, False
    answer = mimics.dialogs.question_box(
        message=empty_mask_preview(empty_masks, runtime)
        + "\n\nChoose one outcome for all, or review them individually.",
        buttons=";".join([BUTTON_ALL_ABSENT, BUTTON_ALL_REVIEW, BUTTON_REVIEW_ONE_BY_ONE, BUTTON_CANCEL]),
        title="Empty Masks",
        ui_blocking=True,
    )
    if answer == BUTTON_CANCEL:
        return None, False
    if answer == BUTTON_ALL_ABSENT:
        return dict(((target_id, organ), "confirmed_absent") for target_id, organ in empty_masks), False
    if answer == BUTTON_ALL_REVIEW:
        return dict(((target_id, organ), "uncertain") for target_id, organ in empty_masks), True

    outcomes = {}
    needs_review = False
    for target_id, organ in empty_masks:
        item_answer = mimics.dialogs.question_box(
            message="{0}/{1} is empty. Confirm why.".format(target_id, organ),
            buttons="Confirmed Absent;Needs Review;Cancel",
            title="Empty Mask",
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


def main(action_override=None):
    runtime = discover_runtime()
    action = normalize_action(action_override)
    if action == "cancel":
        return 0
    target_ids = choose_targets(runtime)
    if not target_ids:
        return 0
    reason_code = choose_reason(action) if action in ("submit_for_review", "report_blocked") else None
    if action in ("submit_for_review", "report_blocked") and reason_code is None:
        return 0

    final_submission_root = runtime["submissions_dir"]
    cleanup_staging(final_submission_root)
    staging_root = final_submission_root + ".partial_{0}".format(os.getpid())
    if os.path.isdir(staging_root):
        shutil.rmtree(staging_root)
    submission_root = staging_root
    if not os.path.isdir(submission_root):
        os.makedirs(submission_root)
    selected_targets = [target for target in runtime["targets"] if target["target_id"] in target_ids]
    base_labels = {}
    entries = []
    organ_outcomes = {}

    if action != "report_blocked":
        if not confirm_unmanaged_masks_ignored(runtime):
            return 0
        findings, empty_masks = preflight_targets(runtime, selected_targets)
        if findings:
            show_preflight_failure(runtime, findings)
            return 2
        empty_outcomes, empty_needs_review = resolve_empty_masks(empty_masks, runtime)
        if empty_outcomes is None:
            return 0
        if empty_needs_review:
            if action == "submit_complete":
                confirm = mimics.dialogs.question_box(
                    message=(
                        "At least one empty Mask was marked as needing review.\n\n"
                        "This cannot be submitted as Complete. The submission will be changed to Needs Review."
                    ),
                    buttons=BUTTON_REVIEW + ";" + BUTTON_CANCEL,
                    title="Submit Type Changed",
                    ui_blocking=True,
                )
                if confirm != BUTTON_REVIEW:
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
        "submission_id": "submission_" + uuid.uuid4().hex,
        "review_id": runtime["review_id"],
        "worklist_id": runtime.get("worklist_id"),
        "submitted_at": utc_now(),
        "target_ids": target_ids,
        "action": action,
        "assignee": runtime.get("assignee"),
        "base_labels": base_labels,
        "organ_outcomes": organ_outcomes,
        "reason_code": reason_code,
    }
    write_json(os.path.join(submission_root, "submission_manifest.json"), submission)
    publish_staged_submission(staging_root, final_submission_root)
    mimics.file.save_project(filename=runtime["mcs_path"], save_as_type="Mimics Project Files")
    mimics.dialogs.message_box(
        "The result was exported. Platform QC is still required before any label is verified.\n\n"
        "If Finalize fails, read reports/review_report.json. The next Open also shows the latest QC failure.",
        title="Export Complete",
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
