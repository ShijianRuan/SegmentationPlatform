# -*- coding: utf-8 -*-
"""Single Mimics-side entry point for annotators.

This script is intended to appear in Mimics Scripting Library as
"SP Review Console". It keeps platform preparation and QC out of the
annotator's command-line workflow.
"""

from __future__ import print_function

import json
import os
import subprocess
import sys

import mimics

from sp_common import load_json, managed_masks, metadata_get, write_error_report


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def console_config_path():
    explicit = os.environ.get("SP_REVIEW_CONSOLE_CONFIG")
    if explicit:
        return explicit
    return os.path.join(SCRIPT_DIR, "sp_review_console.local.json")


def load_console_config():
    path = console_config_path()
    if not os.path.isfile(path):
        raise RuntimeError(
            "SP Review Console config not found: {0}\n"
            "Set SP_REVIEW_CONSOLE_CONFIG or create sp_review_console.local.json.".format(path)
        )
    config = load_json(path)
    required = ("platform_python", "registry_root", "workstation_config", "assignee")
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise RuntimeError("SP Review Console config is missing: {0}".format(", ".join(missing)))
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
            "Close the current project before opening the next assigned review?"
        ),
        buttons="Close Without Saving;Cancel",
        title="SP Review Console",
        ui_blocking=True,
    )
    if answer != "Close Without Saving":
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
            "No assigned review is ready on this workstation.",
            title="SP Review Console",
            ui_blocking=True,
        )
        return 0
    return open_review(config, result["package_path"], result["review_id"])


def submit_current_review(config):
    import sp_submit_review

    result = sp_submit_review.main()
    if result != 0:
        return result
    if config.get("auto_finalize", False):
        context = current_review_context()
        if context:
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
            mimics.dialogs.message_box(
                "Platform QC finished: {0}".format(finalize.get("status", "unknown")),
                title="SP Review Console",
                ui_blocking=True,
            )
    return 0


def save_current_checkpoint():
    import sp_save_checkpoint

    return sp_save_checkpoint.main()


def choose_console_action(has_context):
    if has_context:
        answer = mimics.dialogs.question_box(
            message="Choose the platform action for the current review.",
            buttons="Submit Current Review;Save Checkpoint;Open Next Review;Cancel",
            title="SP Review Console",
            ui_blocking=True,
        )
        return {
            "Submit Current Review": "submit",
            "Save Checkpoint": "checkpoint",
            "Open Next Review": "next",
            "Cancel": "cancel",
        }.get(answer, "cancel")
    answer = mimics.dialogs.question_box(
        message="No platform review is open in this Mimics session.",
        buttons="Open Next Review;Cancel",
        title="SP Review Console",
        ui_blocking=True,
    )
    return "next" if answer == "Open Next Review" else "cancel"


def main():
    config = load_console_config()
    context = current_review_context()
    action = choose_console_action(context is not None)
    if action == "cancel":
        return 0
    if action == "submit":
        return submit_current_review(config)
    if action == "checkpoint":
        return save_current_checkpoint()
    if action == "next":
        if context is not None:
            close = mimics.dialogs.question_box(
                message=(
                    "Save the current project as progress only, close it, and open the next assigned review?\n\n"
                    "This does not submit the current review."
                ),
                buttons="Save Progress And Continue;Cancel",
                title="SP Review Console",
                ui_blocking=True,
            )
            if close != "Save Progress And Continue":
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
                "SP Review Console failed.\n\n{0}\n\nReport: {1}".format(str(error), report_path),
                title="SP Review Console",
                ui_blocking=True,
            )
        finally:
            raise
