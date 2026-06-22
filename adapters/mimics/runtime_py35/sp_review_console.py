# -*- coding: utf-8 -*-
"""Single Mimics-side entry point for annotators.

This module backs the user-facing Start_Labeling.py Scripting Library entry.
It keeps platform preparation and QC out of the annotator's command-line
workflow.
"""

from __future__ import print_function

import json
import os
import subprocess
import sys

import mimics

from sp_common import load_json, managed_masks, metadata_get, write_error_report


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONSOLE_TITLE = "Labeling Task"
TASK_LIST_PAGE_SIZE = 20

TASK_FILTER_ALL = "All"
TASK_FILTER_MISSING = "Missing"
TASK_FILTER_READY = "Ready"
TASK_FILTER_INITIAL = "With Initial"
TASK_FILTER_KNOWN_ABSENT = "Known Absent"

TASK_BUTTON_PREV_PAGE = "Previous Page"
TASK_BUTTON_NEXT_PAGE = "Next Page"
TASK_BUTTON_FILTER = "Filter"
TASK_BUTTON_CLOSE = "Close"

BUTTON_COMPLETE = "Complete"
BUTTON_REVIEW = "Needs Review"
BUTTON_PROBLEM = "Report Problem"
BUTTON_BACKUP = "Save Recovery Backup"
BUTTON_SUMMARY = "Task List"
BUTTON_NEXT = "Next Case"
BUTTON_SKIP = "Skip Case"
BUTTON_START = "Start Next Case"
BUTTON_CANCEL = "Cancel"

BUTTON_SAVE_AND_NEXT = "Save Progress And Open Next"
BUTTON_CLOSE_UNMANAGED = "Close Current Data"

QC_ACTION_BY_CODE = {
    "assignee_mismatch": "Ask the platform operator to check assignment. Do not resubmit from this workstation.",
    "base_label_mismatch": "Stop this task and ask the platform operator to rebuild or reopen it; the base label version changed.",
    "unexpected_base_label": "Ask the platform operator to check the task setup before resubmitting.",
    "missing_mask": "Reopen the case, check the listed organ Mask exists, then submit again.",
    "uncertain_complete": "Use Needs Review for uncertain organs, or resolve the uncertainty before choosing Complete.",
    "invalid_organ_outcome": "Submit again from Start Labeling. If this repeats, ask the platform operator to inspect the task.",
    "image_id_mismatch": "Do not manually edit files. Ask the platform operator to check the image/series binding.",
    "empty_mask": "If the organ is absent, mark it Confirmed Absent; otherwise draw or fix the Mask and submit again.",
}

ADMIN_ONLY_CODE_WORDS = ("hash", "geometry", "shape", "spacing", "origin", "direction", "image_id")


def console_config_path():
    explicit = os.environ.get("SP_REVIEW_CONSOLE_CONFIG")
    if explicit:
        return explicit
    return os.path.join(SCRIPT_DIR, "sp_review_console.local.json")


def load_console_config():
    path = console_config_path()
    if not os.path.isfile(path):
        raise RuntimeError(
            "Labeling task config not found: {0}\n"
            "Set SP_REVIEW_CONSOLE_CONFIG or create sp_review_console.local.json.".format(path)
        )
    config = load_json(path)
    required = ("platform_python", "registry_root", "workstation_config", "assignee")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError("Labeling task config is missing: {0}".format(", ".join(missing)))
    return config


def run_platform(config, args):
    command = [config["platform_python"], "-m", "segplatform"] + list(args)
    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as error:
        text = error.output.decode("utf-8", "replace") if error.output else ""
        raise RuntimeError("Platform command failed:\n{0}\n{1}".format(" ".join(command), text))
    return json.loads(output.decode("utf-8"))


def current_review_context():
    masks = managed_masks(mimics)
    if not masks:
        return None
    review_ids = set(metadata_get(mask, "sp.review_id", "") for mask in masks)
    package_roots = set(metadata_get(mask, "sp.package_root", "") for mask in masks)
    if len(review_ids) != 1 or "" in review_ids or len(package_roots) != 1 or "" in package_roots:
        raise RuntimeError("Current project has inconsistent SegmentationPlatform metadata")
    return {
        "review_id": list(review_ids)[0],
        "package_root": list(package_roots)[0],
    }


def collection_has_items(collection):
    try:
        for _item in collection:
            return True
    except Exception:
        return False
    return False


def has_unmanaged_project_data():
    return collection_has_items(mimics.data.images) or collection_has_items(mimics.data.masks)


def close_unmanaged_project_if_needed():
    if not has_unmanaged_project_data():
        return True
    answer = mimics.dialogs.question_box(
        message=(
            "This Mimics session already contains data that is not managed by SegmentationPlatform.\n\n"
            "Close the current data before starting the next assigned case?"
        ),
        buttons=BUTTON_CLOSE_UNMANAGED + ";" + BUTTON_CANCEL,
        title=CONSOLE_TITLE,
        ui_blocking=True,
    )
    if answer != BUTTON_CLOSE_UNMANAGED:
        return False
    mimics.file.close_project()
    return True


def console_error_report_path():
    try:
        context = current_review_context()
        if context and context.get("package_root"):
            return os.path.join(context["package_root"], "reports", "mimics_review_console_error.json")
    except Exception:
        pass
    return os.path.join(SCRIPT_DIR, "sp_review_console_error.json")


def open_review(config, package_root, review_id):
    prepare_result = run_platform(
        config,
        ["mimics", "prepare", package_root, "--config", config["workstation_config"]],
    )
    run_platform(
        config,
        [
            "review",
            "start",
            "--registry",
            config["registry_root"],
            "--review-id",
            review_id,
            "--actor",
            config["assignee"],
        ],
    )
    import sp_open_review

    original_argv = list(sys.argv)
    try:
        sys.argv = ["sp_open_review.py", prepare_result["runtime_manifest"]]
        return sp_open_review.main()
    finally:
        sys.argv = original_argv


def open_next_review(config, exclude_review_id=None):
    args = ["review", "next", "--registry", config["registry_root"], "--assignee", config["assignee"]]
    if exclude_review_id:
        args.extend(["--exclude-review-id", exclude_review_id])
    result = run_platform(config, args)
    if result.get("status") == "empty":
        mimics.dialogs.message_box(
            "No assigned case is ready on this workstation.",
            title=CONSOLE_TITLE,
            ui_blocking=True,
        )
        return 0
    return open_review(config, result["package_path"], result["review_id"])


def submit_current_review(config, action):
    import sp_submit_review

    result = sp_submit_review.main(action)
    if result != 0:
        return result
    if config.get("auto_finalize", False):
        context = current_review_context()
        if context:
            try:
                finalize = run_platform(
                    config,
                    [
                        "mimics",
                        "finalize",
                        context["package_root"],
                        "--config",
                        config["workstation_config"],
                        "--registry",
                        config["registry_root"],
                    ],
                )
            except Exception as error:
                mimics.dialogs.message_box(
                    build_qc_failure_message(context["package_root"], error),
                    title="Platform QC Failed",
                    ui_blocking=True,
                )
                return 2
            mimics.dialogs.message_box(
                "Platform QC finished: {0}".format(finalize.get("status", "unknown")),
                title=CONSOLE_TITLE,
                ui_blocking=True,
            )
    return 0


def finding_action(finding):
    code = str(finding.get("code") or "")
    if code in QC_ACTION_BY_CODE:
        return QC_ACTION_BY_CODE[code]
    lowered = code.lower() + " " + str(finding.get("message") or "").lower()
    for word in ADMIN_ONLY_CODE_WORDS:
        if word in lowered:
            return "Do not manually edit files. Ask the platform operator to inspect the package and geometry."
    return "Reopen this case from Start Labeling. If you cannot fix the listed Mask, choose Needs Review or Report Problem."


def _short_text(value, limit):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def build_qc_failure_message(package_root, error):
    report_path = os.path.join(package_root, "reports", "review_report.json")
    report = None
    if os.path.isfile(report_path):
        try:
            report = load_json(report_path)
        except Exception:
            report = None
    if report and report.get("findings"):
        findings = list(report.get("findings", []))
        lines = [
            "Platform QC did not accept this submission.",
            "",
            "What to do:",
        ]
        for index, finding in enumerate(findings[:4], start=1):
            code = str(finding.get("code") or "qc_issue")
            message = _short_text(finding.get("message") or code, 140)
            action = finding_action(finding)
            lines.append("{0}. {1}: {2}".format(index, code, message))
            lines.append("   Action: {0}".format(action))
        if len(findings) > 4:
            lines.append("... {0} more issue(s) in the report.".format(len(findings) - 4))
        lines.extend(
            [
                "",
                "Your work was not verified yet. Save the Mimics project before leaving.",
                "Technical report: {0}".format(report_path),
            ]
        )
        return "\n".join(lines)
    return (
        "Platform QC could not finish. This may be a platform or file issue, not necessarily a Mask issue.\n\n"
        "Action: save the Mimics project and ask the platform operator to inspect the report/logs before resubmitting.\n\n"
        "Technical error: {0}\n"
        "Expected report: {1}".format(_short_text(str(error), 300), report_path)
    )


def save_current_checkpoint(config):
    import sp_save_checkpoint

    return sp_save_checkpoint.main(config.get("checkpoint_keep_count", 3))


def skip_current_review(config, context):
    run_platform(
        config,
        [
            "review",
            "defer",
            "--registry",
            config["registry_root"],
            "--review-id",
            context["review_id"],
            "--actor",
            config["assignee"],
            "--reason",
            "skipped_by_annotator",
        ],
    )
    mimics.file.save_project()
    mimics.file.close_project()
    return open_next_review(config, exclude_review_id=context["review_id"])


def current_mask_state(review_id):
    result = {}
    for mask in managed_masks(mimics, review_id):
        target_id = metadata_get(mask, "sp.target_id", "")
        organ = metadata_get(mask, "sp.organ", "")
        image_id = metadata_get(mask, "sp.image_id", "")
        if target_id and organ:
            result[(target_id, organ)] = {
                "mask_name": getattr(mask, "name", ""),
                "image_id": image_id,
            }
    return result


def import_buffer_state(runtime):
    result = set()
    for entry in runtime.get("import_buffers", []):
        result.add((entry.get("image_id", ""), entry.get("organ", "")))
    for entry in runtime.get("checkpoint_buffers", []):
        result.add((entry.get("image_id", ""), entry.get("organ", "")))
    return result


def task_list_model(runtime, mask_state, import_state):
    entries = []
    counts = {
        "total": 0,
        "ready": 0,
        "missing": 0,
        "known_absent": 0,
        "initial": 0,
    }
    for target in runtime.get("targets", []):
        target_id = target.get("target_id", "")
        image_id = target.get("image_id", "")
        known_absent = set(target.get("known_absent", []))
        organs = target.get("organs", [])
        if not organs:
            organs = [mask.get("organ", "") for mask in target.get("masks", [])]
        for organ in organs:
            counts["total"] += 1
            key = (target_id, organ)
            labels = []
            status = "missing"
            has_initial = (image_id, organ) in import_state
            if organ in known_absent:
                counts["known_absent"] += 1
                status = "known_absent"
                labels.append("not required: known absent")
            elif key in mask_state:
                counts["ready"] += 1
                status = "ready"
                labels.append("mask ready")
                if has_initial:
                    labels.append("initial/checkpoint")
            else:
                counts["missing"] += 1
                labels.append("mask missing")
                if has_initial:
                    labels.append("initial/checkpoint pending")
            if has_initial:
                counts["initial"] += 1
            entries.append(
                {
                    "target_id": target_id,
                    "image_id": image_id,
                    "organ": organ,
                    "status": status,
                    "has_initial": has_initial,
                    "labels": labels,
                    "target_organ_count": len(organs),
                }
            )
    return {
        "case_id": runtime.get("case_id", ""),
        "review_id": runtime.get("review_id", ""),
        "target_count": len(runtime.get("targets", [])),
        "entries": entries,
        "counts": counts,
    }


def task_counts_line(model):
    counts = model["counts"]
    return "Organs: {0}; ready masks: {1}; missing masks: {2}; known absent: {3}; with initial: {4}".format(
        counts["total"], counts["ready"], counts["missing"], counts["known_absent"], counts["initial"]
    )


def task_entry_full_line(entry):
    return "  - {0} [{1}]".format(entry["organ"], ", ".join(entry["labels"]))


def task_entry_page_line(index, entry):
    return "{0}. {1} [{2}] | image {3} / group {4}".format(
        index,
        entry["organ"],
        ", ".join(entry["labels"]),
        entry["image_id"],
        entry["target_id"],
    )


def task_list_full_text(model):
    lines = [
        "Case: {0}".format(model["case_id"]),
        "Internal review id: {0}".format(model["review_id"]),
        task_counts_line(model),
        "",
        "Targets:",
    ]
    previous_group = None
    for entry in model["entries"]:
        group = (entry["image_id"], entry["target_id"])
        if group != previous_group:
            lines.append(
                "- Image {0} / group {1}: {2} organ(s)".format(
                    entry["image_id"], entry["target_id"], entry["target_organ_count"]
                )
            )
            previous_group = group
        lines.append(task_entry_full_line(entry))
    return "\n".join(lines)


def task_filter_matches(entry, status_filter):
    if status_filter == TASK_FILTER_ALL:
        return True
    if status_filter == TASK_FILTER_MISSING:
        return entry["status"] == "missing"
    if status_filter == TASK_FILTER_READY:
        return entry["status"] == "ready"
    if status_filter == TASK_FILTER_INITIAL:
        return entry["has_initial"]
    if status_filter == TASK_FILTER_KNOWN_ABSENT:
        return entry["status"] == "known_absent"
    return True


def filtered_task_entries(model, status_filter):
    return [entry for entry in model["entries"] if task_filter_matches(entry, status_filter)]


def task_page_count(entry_count):
    if entry_count <= 0:
        return 1
    return int((entry_count + TASK_LIST_PAGE_SIZE - 1) / TASK_LIST_PAGE_SIZE)


def clamp_task_page(page_index, entry_count):
    page_count = task_page_count(entry_count)
    if page_index < 0:
        return 0
    if page_index >= page_count:
        return page_count - 1
    return page_index


def task_list_page_text(model, status_filter, page_index, summary_path=None):
    entries = filtered_task_entries(model, status_filter)
    page_index = clamp_task_page(page_index, len(entries))
    page_count = task_page_count(len(entries))
    start = page_index * TASK_LIST_PAGE_SIZE
    end = min(start + TASK_LIST_PAGE_SIZE, len(entries))
    lines = [
        "Case: {0}".format(model["case_id"]),
        "Targets: {0}".format(model["target_count"]),
        task_counts_line(model),
        "Filter: {0}; Page {1}/{2}; Showing {3}-{4} of {5}".format(
            status_filter,
            page_index + 1,
            page_count,
            start + 1 if entries else 0,
            end,
            len(entries),
        ),
        "",
    ]
    if not entries:
        lines.append("No organs match this filter.")
    else:
        for offset, entry in enumerate(entries[start:end], start=start + 1):
            lines.append(task_entry_page_line(offset, entry))
    lines.extend(
        [
            "",
            "Use Filter for Missing, Ready, With Initial, or Known Absent.",
        ]
    )
    if summary_path:
        lines.append("Full text report: {0}".format(summary_path))
    return "\n".join(lines)


def task_summary(runtime, mask_state, import_state):
    model = task_list_model(runtime, mask_state, import_state)
    full_text = task_list_full_text(model)
    preview_text = task_list_page_text(model, TASK_FILTER_ALL, 0)
    truncated = len(model["entries"]) > TASK_LIST_PAGE_SIZE
    return full_text, preview_text, truncated


def write_text(path, text):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(text)
        handle.write("\n")


def choose_task_filter(current_filter):
    answer = mimics.dialogs.question_box(
        message="Show which organs?",
        buttons=";".join(
            [
                TASK_FILTER_ALL,
                TASK_FILTER_MISSING,
                TASK_FILTER_READY,
                TASK_FILTER_INITIAL,
                TASK_FILTER_KNOWN_ABSENT,
                BUTTON_CANCEL,
            ]
        ),
        title="Task List Filter",
        ui_blocking=True,
    )
    if answer in (
        TASK_FILTER_ALL,
        TASK_FILTER_MISSING,
        TASK_FILTER_READY,
        TASK_FILTER_INITIAL,
        TASK_FILTER_KNOWN_ABSENT,
    ):
        return answer
    return current_filter


def show_task_list_dialog(model, summary_path):
    status_filter = TASK_FILTER_ALL
    page_index = 0
    while True:
        entries = filtered_task_entries(model, status_filter)
        page_index = clamp_task_page(page_index, len(entries))
        page_count = task_page_count(len(entries))
        buttons = []
        if page_index > 0:
            buttons.append(TASK_BUTTON_PREV_PAGE)
        if page_index < page_count - 1:
            buttons.append(TASK_BUTTON_NEXT_PAGE)
        buttons.append(TASK_BUTTON_FILTER)
        buttons.append(TASK_BUTTON_CLOSE)
        answer = mimics.dialogs.question_box(
            message=task_list_page_text(model, status_filter, page_index, summary_path),
            buttons=";".join(buttons),
            title="Task List",
            ui_blocking=True,
        )
        if answer == TASK_BUTTON_NEXT_PAGE:
            page_index += 1
        elif answer == TASK_BUTTON_PREV_PAGE:
            page_index -= 1
        elif answer == TASK_BUTTON_FILTER:
            status_filter = choose_task_filter(status_filter)
            page_index = 0
        else:
            return 0


def show_current_summary(context):
    runtime_path = os.path.join(context["package_root"], "working", "mimics_runtime.json")
    runtime = load_json(runtime_path)
    mask_state = current_mask_state(runtime.get("review_id", ""))
    import_state = import_buffer_state(runtime)
    model = task_list_model(runtime, mask_state, import_state)
    full_text = task_list_full_text(model)
    summary_path = os.path.join(runtime.get("reports_dir", os.path.join(context["package_root"], "reports")), "mimics_task_list.txt")
    write_text(summary_path, full_text)
    if hasattr(mimics.dialogs, "question_box"):
        return show_task_list_dialog(model, summary_path)
    mimics.dialogs.message_box(
        task_list_page_text(model, TASK_FILTER_ALL, 0, summary_path),
        title="Task List",
        ui_blocking=True,
    )
    return 0


def choose_console_action(has_context):
    if has_context:
        answer = mimics.dialogs.question_box(
            message="Choose the result or action for the current case.",
            buttons=";".join(
                [
                    BUTTON_COMPLETE,
                    BUTTON_REVIEW,
                    BUTTON_PROBLEM,
                    BUTTON_SUMMARY,
                    BUTTON_BACKUP,
                    BUTTON_SKIP,
                    BUTTON_NEXT,
                    BUTTON_CANCEL,
                ]
            ),
            title=CONSOLE_TITLE,
            ui_blocking=True,
        )
        return {
            BUTTON_COMPLETE: "submit_complete",
            BUTTON_REVIEW: "submit_for_review",
            BUTTON_PROBLEM: "report_blocked",
            BUTTON_BACKUP: "checkpoint",
            BUTTON_SUMMARY: "summary",
            BUTTON_SKIP: "skip",
            BUTTON_NEXT: "next",
            BUTTON_CANCEL: "cancel",
        }.get(answer, "cancel")
    answer = mimics.dialogs.question_box(
        message="No platform case is open in this Mimics session.",
        buttons=BUTTON_START + ";" + BUTTON_CANCEL,
        title=CONSOLE_TITLE,
        ui_blocking=True,
    )
    return "next" if answer == BUTTON_START else "cancel"


def main():
    config = load_console_config()
    context = current_review_context()
    action = choose_console_action(context is not None)
    if action == "cancel":
        return 0
    if action in ("submit_complete", "submit_for_review", "report_blocked"):
        return submit_current_review(config, action)
    if action == "checkpoint":
        return save_current_checkpoint(config)
    if action == "summary":
        return show_current_summary(context)
    if action == "skip":
        confirm = mimics.dialogs.question_box(
            message=(
                "Skip this case for now and open the next assigned case?\n\n"
                "This does not submit the current work and does not mark the case as impossible."
            ),
            buttons=BUTTON_SKIP + ";" + BUTTON_CANCEL,
            title=CONSOLE_TITLE,
            ui_blocking=True,
        )
        if confirm != BUTTON_SKIP:
            return 0
        return skip_current_review(config, context)
    if action == "next":
        if context is not None:
            close = mimics.dialogs.question_box(
                message=(
                    "Save the current project as progress only, close it, and open the next assigned case?\n\n"
                    "This does not submit the current work."
                ),
                buttons=BUTTON_SAVE_AND_NEXT + ";" + BUTTON_CANCEL,
                title=CONSOLE_TITLE,
                ui_blocking=True,
            )
            if close != BUTTON_SAVE_AND_NEXT:
                return 0
            mimics.file.save_project()
            mimics.file.close_project()
        elif not close_unmanaged_project_if_needed():
            return 0
        return open_next_review(config, exclude_review_id=context["review_id"] if context else None)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        try:
            report_path = os.path.abspath(console_error_report_path())
            write_error_report(report_path, "review_console", error)
            mimics.dialogs.message_box(
                "The labeling task action failed.\n\n{0}\n\nReport: {1}".format(str(error), report_path),
                title=CONSOLE_TITLE,
                ui_blocking=True,
            )
        finally:
            raise
