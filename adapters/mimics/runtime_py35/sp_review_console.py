# -*- coding: utf-8 -*-
"""Self-contained Mimics worklist console for annotators.

The worklist is movable and has no dependency on SegmentationPlatform Python,
a Registry, a workstation YAML file, or an assignee-specific local config.
"""

from __future__ import print_function

import os
import sys
import time

import mimics

from sp_common import load_json, managed_masks, metadata_get, write_error_report, write_json


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

BUTTON_SKIP = "Skip Case"
BUTTON_CANCEL = "Cancel"
BUTTON_CONTINUE = "Continue Last Case"
BUTTON_CHOOSE = "Choose Case"
BUTTON_NEEDS_REVIEW = "Needs Review"
BUTTON_REPORT_PROBLEM = "Report Problem"

BUTTON_SAVE_AND_NEXT = "Save Progress And Open Next"
BUTTON_CLOSE_UNMANAGED = "Close Current Data"

CASE_PAGE_SIZE = 8
BUTTON_PREVIOUS_CASES = "Previous Cases"
BUTTON_NEXT_CASES = "Next Cases"


def worklist_root():
    explicit = os.environ.get("SP_WORKLIST_ROOT")
    candidates = [
        explicit,
        os.path.dirname(SCRIPT_DIR),
        os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..")),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "worklist_manifest.json")):
            return os.path.abspath(candidate)
    raise RuntimeError(
        "worklist_manifest.json was not found.\n\n"
        "Run a Labeling_*.py entry from the root of an exported Mimics worklist."
    )


def load_worklist():
    root = worklist_root()
    manifest = load_json(os.path.join(root, "worklist_manifest.json"))
    if manifest.get("schema_version") != "mimics_worklist.v2":
        raise RuntimeError("Unsupported worklist schema: {0}".format(manifest.get("schema_version")))
    review_ids = [entry.get("review_id") for entry in manifest.get("reviews", [])]
    if not review_ids or len(review_ids) != len(set(review_ids)):
        raise RuntimeError("The worklist has no cases or contains duplicate review ids")
    return root, manifest


def load_worklist_state(root, manifest):
    path = os.path.join(root, manifest.get("state_path", "worklist_progress.json"))
    if os.path.isfile(path):
        state = load_json(path)
    else:
        state = {}
    if (
        state.get("schema_version") != "mimics_worklist_progress.v1"
        or state.get("worklist_id") != manifest.get("worklist_id")
    ):
        state = {
            "schema_version": "mimics_worklist_progress.v1",
            "worklist_id": manifest.get("worklist_id"),
            "current_review_id": None,
            "items": {},
        }
    state.setdefault("items", {})
    return path, state


def save_worklist_state(path, state):
    write_json(path, state)


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def entry_package_root(root, entry):
    return os.path.abspath(os.path.join(root, entry["package_path"]))


def entry_runtime_path(root, entry):
    return os.path.abspath(os.path.join(root, entry["runtime_path"]))


def entry_submission_path(root, entry):
    return os.path.join(
        entry_package_root(root, entry),
        "submissions",
        entry["review_id"],
        "submission_manifest.json",
    )


def submission_info(root, entry, worklist_id=None):
    path = entry_submission_path(root, entry)
    if not os.path.isfile(path):
        return None
    submission = load_json(path)
    if worklist_id and submission.get("worklist_id") != worklist_id:
        return None
    action = submission.get("action")
    status = {
        "submit_complete": "submitted",
        "submit_for_review": "submitted_for_review",
        "report_blocked": "reported_problem",
    }.get(action, "submitted")
    submission_key = (
        submission.get("submission_id")
        or submission.get("submitted_at")
        or "legacy:{0}".format(action or "submitted")
    )
    return {
        "status": status,
        "submission_key": submission_key,
        "submitted_at": submission.get("submitted_at"),
    }


def submission_status(root, entry, worklist_id=None):
    info = submission_info(root, entry, worklist_id)
    return info.get("status") if info else None


def refresh_worklist_state(root, manifest, state):
    for entry in manifest["reviews"]:
        item = state["items"].setdefault(entry["review_id"], {})
        submitted = submission_info(root, entry, manifest.get("worklist_id"))
        if submitted:
            reopened_after_submission = (
                item.get("status") in ("in_progress", "deferred")
                and item.get("last_submission_key") == submitted["submission_key"]
            )
            if not reopened_after_submission:
                item["status"] = submitted["status"]
            item["last_submission_key"] = submitted["submission_key"]
            if submitted.get("submitted_at"):
                item["last_submitted_at"] = submitted["submitted_at"]
        else:
            item.setdefault("status", "available")
    return state


def _rebase_case_path(value, old_root, new_root):
    if not value:
        return value
    path = str(value)
    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(new_root, path))
    try:
        relative = os.path.relpath(path, old_root)
    except (TypeError, ValueError):
        return path
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return path
    return os.path.abspath(os.path.join(new_root, relative))


def rebase_runtime(runtime, package_root, worklist_id, submission_assignee=None):
    old_root = os.path.abspath(runtime.get("package_root") or package_root)
    runtime["package_root"] = package_root
    runtime["worklist_id"] = worklist_id
    runtime["assignee"] = submission_assignee
    for key in (
        "mcs_path",
        "prebuilt_marker_path",
        "dicom_import_root",
        "reports_dir",
        "submissions_dir",
        "buffer_manifest",
    ):
        runtime[key] = _rebase_case_path(runtime.get(key), old_root, package_root)
    for image in runtime.get("image_sets", []):
        for key in ("dicom_path", "image_path"):
            image[key] = _rebase_case_path(image.get(key), old_root, package_root)
    for collection_name in ("import_buffers", "checkpoint_buffers"):
        for entry in runtime.get(collection_name, []):
            entry["path"] = _rebase_case_path(entry.get("path"), old_root, package_root)
    if os.path.isfile(runtime.get("mcs_path", "")):
        marker = runtime.get("prebuilt_marker_path", "")
        runtime["mode"] = "prebuilt" if marker and os.path.isfile(marker) else "resume"
    else:
        runtime["mode"] = "new"
    return runtime


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
            "This Mimics session already contains other image or Mask data.\n\n"
            "Close the current data before opening a worklist case?"
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


def open_review(root, manifest, state_path, state, entry):
    package_root = entry_package_root(root, entry)
    runtime_manifest = entry_runtime_path(root, entry)
    if not os.path.isfile(runtime_manifest):
        raise RuntimeError("Prepared Mimics runtime is missing: {0}".format(runtime_manifest))
    runtime = load_json(runtime_manifest)
    runtime = rebase_runtime(
        runtime,
        package_root,
        manifest.get("worklist_id"),
        entry.get("submission_assignee"),
    )
    write_json(runtime_manifest, runtime)
    import sp_open_review

    original_argv = list(sys.argv)
    try:
        sys.argv = ["sp_open_review.py", runtime_manifest]
        result = sp_open_review.main()
    except Exception:
        # sp_open_review may have imported DICOM or created managed masks before
        # failing; drop the partially initialized project so the Mimics session is
        # not left with inconsistent state, then re-raise so the caller reports it.
        try:
            mimics.file.close_project()
        except Exception:
            pass
        raise
    finally:
        sys.argv = original_argv
    item = state["items"].setdefault(entry["review_id"], {})
    item["status"] = "in_progress"
    item["last_opened_at"] = utc_now()
    state["current_review_id"] = entry["review_id"]
    save_worklist_state(state_path, state)
    return result


def find_worklist_entry(manifest, review_id):
    for entry in manifest["reviews"]:
        if entry["review_id"] == review_id:
            return entry
    return None


def next_worklist_entry(root, manifest, state, exclude_review_id=None):
    priorities = ("available", "in_progress", "deferred")
    for desired_status in priorities:
        for entry in manifest["reviews"]:
            if entry["review_id"] == exclude_review_id:
                continue
            item = state["items"].setdefault(entry["review_id"], {"status": "available"})
            if item.get("status") == desired_status:
                return entry
    return None


def open_next_review(root, manifest, state_path, state, exclude_review_id=None):
    refresh_worklist_state(root, manifest, state)
    entry = next_worklist_entry(root, manifest, state, exclude_review_id=exclude_review_id)
    if entry is None:
        mimics.dialogs.message_box(
            "No unfinished case remains in this worklist.\n\n"
            "Use Choose Case to reopen a submitted or previously reported case.",
            title=CONSOLE_TITLE,
            ui_blocking=True,
        )
        return 0
    return open_review(root, manifest, state_path, state, entry)


def submit_current_review(root, manifest, state_path, state, action):
    import sp_submit_review

    result = sp_submit_review.main(action)
    if result != 0:
        return result
    context = current_review_context()
    if context:
        entry = find_worklist_entry(manifest, context["review_id"])
        if entry:
            submitted = submission_info(root, entry, manifest.get("worklist_id"))
            item = state["items"].setdefault(context["review_id"], {})
            item["status"] = submitted["status"] if submitted else "in_progress"
            if submitted:
                item["last_submission_key"] = submitted["submission_key"]
            item["last_submitted_at"] = utc_now()
            save_worklist_state(state_path, state)
    return 0


def save_current_checkpoint(manifest):
    import sp_save_checkpoint

    return sp_save_checkpoint.main(int(manifest.get("checkpoint_keep_count", 3)))


def skip_current_review(root, manifest, state_path, state, context):
    item = state["items"].setdefault(context["review_id"], {})
    item["status"] = "deferred"
    item["last_deferred_at"] = utc_now()
    state["current_review_id"] = None
    save_worklist_state(state_path, state)
    mimics.file.save_project()
    mimics.file.close_project()
    return open_next_review(
        root,
        manifest,
        state_path,
        state,
        exclude_review_id=context["review_id"],
    )


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


def worklist_case_status(state, review_id):
    return state["items"].get(review_id, {}).get("status", "available")


def choose_worklist_entry(manifest, state):
    page_index = 0
    entries = manifest["reviews"]
    while True:
        page_count = max(1, int((len(entries) + CASE_PAGE_SIZE - 1) / CASE_PAGE_SIZE))
        page_index = max(0, min(page_index, page_count - 1))
        start = page_index * CASE_PAGE_SIZE
        page = entries[start:start + CASE_PAGE_SIZE]
        buttons = [str(index + 1) for index in range(len(page))]
        if page_index > 0:
            buttons.append(BUTTON_PREVIOUS_CASES)
        if page_index < page_count - 1:
            buttons.append(BUTTON_NEXT_CASES)
        buttons.append(BUTTON_CANCEL)
        lines = [
            "Choose any case in this worklist.",
            "Submitted cases can be reopened and submitted again.",
            "",
        ]
        for index, entry in enumerate(page):
            lines.append(
                "{0}. {1} [{2}]".format(
                    index + 1,
                    entry.get("case_id", entry["review_id"]),
                    worklist_case_status(state, entry["review_id"]),
                )
            )
        lines.extend(["", "Page {0}/{1}".format(page_index + 1, page_count)])
        answer = mimics.dialogs.question_box(
            message="\n".join(lines),
            buttons=";".join(buttons),
            title="Choose Case",
            ui_blocking=True,
        )
        if answer == BUTTON_PREVIOUS_CASES:
            page_index -= 1
        elif answer == BUTTON_NEXT_CASES:
            page_index += 1
        elif answer == BUTTON_CANCEL:
            return None
        else:
            try:
                selected = int(answer) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= selected < len(page):
                return page[selected]


def require_current_context(context, action_name):
    if context is not None:
        return True
    mimics.dialogs.message_box(
        "No worklist case is currently open.\n\n"
        "Open or continue a case before using {0}.".format(action_name),
        title=CONSOLE_TITLE,
        ui_blocking=True,
    )
    return False


def choose_navigation_action(context, can_continue):
    buttons = []
    if can_continue and (context is None or context.get("review_id") is None):
        buttons.append(BUTTON_CONTINUE)
    buttons.append(BUTTON_CHOOSE)
    if context is not None:
        buttons.append(BUTTON_SKIP)
    buttons.append(BUTTON_CANCEL)
    answer = mimics.dialogs.question_box(
        message=(
            "Continue the last case, choose a different case, or temporarily skip the open case."
        ),
        buttons=";".join(buttons),
        title="Case Navigation",
        ui_blocking=True,
    )
    return {
        BUTTON_CONTINUE: "continue",
        BUTTON_CHOOSE: "choose",
        BUTTON_SKIP: "skip",
        BUTTON_CANCEL: "cancel",
    }.get(answer, "cancel")


def choose_issue_action():
    answer = mimics.dialogs.question_box(
        message=(
            "Use Needs Review when the Mask can be exported but medical judgment remains uncertain.\n\n"
            "Use Report Problem when data or tool issues prevent the case from continuing."
        ),
        buttons=";".join([BUTTON_NEEDS_REVIEW, BUTTON_REPORT_PROBLEM, BUTTON_CANCEL]),
        title="Submit or Report Issue",
        ui_blocking=True,
    )
    return {
        BUTTON_NEEDS_REVIEW: "submit_for_review",
        BUTTON_REPORT_PROBLEM: "report_blocked",
        BUTTON_CANCEL: "cancel",
    }.get(answer, "cancel")


def main(action):
    root, manifest = load_worklist()
    state_path, state = load_worklist_state(root, manifest)
    refresh_worklist_state(root, manifest, state)
    context = current_review_context()
    current_review_id = state.get("current_review_id")
    if action == "navigation":
        action = choose_navigation_action(
            context,
            bool(current_review_id and find_worklist_entry(manifest, current_review_id)),
        )
    elif action == "issue":
        if not require_current_context(context, "Submit or Report Issue"):
            return 0
        action = choose_issue_action()
    if action == "cancel":
        save_worklist_state(state_path, state)
        return 0
    if action in ("submit_complete", "submit_for_review", "report_blocked"):
        if not require_current_context(context, "Submit or Report Current Case"):
            return 0
        return submit_current_review(root, manifest, state_path, state, action)
    if action == "checkpoint":
        if not require_current_context(context, "Save Recovery Backup"):
            return 0
        return save_current_checkpoint(manifest)
    if action == "summary":
        if not require_current_context(context, "View Task List"):
            return 0
        return show_current_summary(context)
    if action == "skip":
        if not require_current_context(context, "Skip Current Case"):
            return 0
        confirm = mimics.dialogs.question_box(
            message=(
                "Skip this case for now and open the next worklist case?\n\n"
                "This does not submit the current work and does not mark the case as impossible."
            ),
            buttons=BUTTON_SKIP + ";" + BUTTON_CANCEL,
            title=CONSOLE_TITLE,
            ui_blocking=True,
        )
        if confirm != BUTTON_SKIP:
            return 0
        return skip_current_review(root, manifest, state_path, state, context)
    if action == "continue":
        entry = find_worklist_entry(manifest, current_review_id)
        if entry is None:
            state["current_review_id"] = None
            save_worklist_state(state_path, state)
            mimics.dialogs.message_box(
                "There is no previous worklist case to continue.\n\n"
                "Use Open Next Case or Choose Case.",
                title=CONSOLE_TITLE,
                ui_blocking=True,
            )
            return 0
        if context is not None and context.get("review_id") == current_review_id:
            return 0
        if not close_unmanaged_project_if_needed():
            return 0
        return open_review(root, manifest, state_path, state, entry)
    if action == "choose":
        entry = choose_worklist_entry(manifest, state)
        if entry is None:
            return 0
        if context is not None and context.get("review_id") == entry.get("review_id"):
            return 0
        if context is not None:
            mimics.file.save_project()
            mimics.file.close_project()
        elif not close_unmanaged_project_if_needed():
            return 0
        return open_review(root, manifest, state_path, state, entry)
    if action == "next":
        if context is not None:
            close = mimics.dialogs.question_box(
                message=(
                    "Save the current project as progress only, close it, and open the next worklist case?\n\n"
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
        return open_next_review(
            root,
            manifest,
            state_path,
            state,
            exclude_review_id=context["review_id"] if context else None,
        )
    return 0


def run_entry(action):
    try:
        return main(action)
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


if __name__ == "__main__":
    requested_action = sys.argv[1] if len(sys.argv) > 1 else ""
    if requested_action not in (
        "next",
        "navigation",
        "continue",
        "choose",
        "submit_complete",
        "issue",
        "submit_for_review",
        "report_blocked",
        "summary",
        "skip",
        "checkpoint",
    ):
        raise RuntimeError(
            "usage: sp_review_console.py "
            "[next|navigation|submit_complete|issue|summary|checkpoint]"
        )
    sys.exit(run_entry(requested_action))
