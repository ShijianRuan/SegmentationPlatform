# -*- coding: utf-8 -*-
"""MIMICS-side nnInteractive refinement script (diff-based, zero-dialog).

This module runs inside MIMICS (Python 3.5.2). It:
1. Auto-detects which mask the annotator is currently editing
2. Computes the diff between the current mask and a saved baseline
   - Newly painted voxels = positive (foreground) scribble
   - Erased voxels     = negative (background) scribble
3. Calls the nnInteractive bridge to refine the segmentation
4. Imports the refined mask and saves a new baseline

Usage from the MIMICS Review Console:
    sp_nninteractive_refine.main(runtime_path)
"""

from __future__ import print_function

import json
import os
import subprocess
import sys
import time
import uuid

import mimics

from sp_common import (
    export_mask_u8,
    load_json,
    match_images,
    managed_masks,
    metadata_get,
    metadata_set,
    set_mask_buffer_from_u8,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
#  Path resolution
# ---------------------------------------------------------------------------

def _project_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find_nninteractive_python():
    root = _project_root()
    candidates = [
        os.environ.get("SP_NNINTERACTIVE_PYTHON", ""),
        # Standard venv layout (created by setup_nninteractive_env.py).
        os.path.join(root, "nninteractive_env", "Scripts", "python.exe"),
        os.path.join(root, "nninteractive_env", "bin", "python"),
        os.path.join(root, "nninteractive_env", "bin", "python3"),
        # Portable bundle layout (created by build_nninteractive_bundle.py).
        os.path.join(root, "nninteractive_env", "python", "python.exe"),
        os.path.join(root, "nninteractive_env", "python", "bin", "python"),
        os.path.join(root, "nninteractive_env", "python", "bin", "python3"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        "nnInteractive Python not found. "
        "Unzip the nninteractive_bundle.zip into your project directory.\n"
    )


def _find_bridge_script():
    candidates = [
        os.environ.get("SP_NNINTERACTIVE_BRIDGE", ""),
        os.path.join(
            _project_root(), "src", "segplatform", "adapters", "mimics",
            "nninteractive_bridge.py",
        ),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise RuntimeError(
        "nnInteractive bridge script not found. Set SP_NNINTERACTIVE_BRIDGE.\n"
    )


def _find_model_dir():
    candidates = [
        os.environ.get("SP_NNINTERACTIVE_MODEL_DIR", ""),
        os.path.join(_project_root(), "nninteractive_env", "models", "nnInteractive_v1.0"),
    ]
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return candidate
    raise RuntimeError(
        "nnInteractive model weights not found. Set SP_NNINTERACTIVE_MODEL_DIR or run setup.\n"
    )


# ---------------------------------------------------------------------------
#  Baseline management (for diff-based interaction)
# ---------------------------------------------------------------------------

def _baseline_path(case_root, target_id, organ):
    """Path to the saved baseline .u8 for a mask."""
    baseline_dir = os.path.join(case_root, "working", "nninteractive", "baselines")
    return os.path.join(baseline_dir, "{0}_{1}_baseline.u8".format(target_id, organ))


def _save_baseline(mask, case_root, target_id, organ):
    """Save the current mask content as the baseline for future diffs."""
    path = _baseline_path(case_root, target_id, organ)
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    export_mask_u8(mask, path)


def _load_baseline_data(case_root, target_id, organ, shape):
    """Load baseline as a byte string, or None if no baseline exists."""
    path = _baseline_path(case_root, target_id, organ)
    if not os.path.isfile(path):
        return None
    raw = open(path, "rb").read()
    expected = int(shape[0]) * int(shape[1]) * int(shape[2])
    if len(raw) != expected:
        return None  # Shape mismatch — baseline is stale.
    return raw


def _compute_diff(current_bytes, baseline_bytes, shape):
    """Compute foreground and background masks from the diff.

    Returns (fg_bytes, bg_bytes, fg_count, bg_count).
    fg = current & ~baseline  (newly painted = positive)
    bg = baseline & ~current  (erased = negative = background)
    """
    import numpy as np

    current = np.frombuffer(current_bytes, dtype=np.uint8).reshape(tuple(shape))
    if baseline_bytes is not None:
        baseline = np.frombuffer(baseline_bytes, dtype=np.uint8).reshape(tuple(shape))
        fg = (current & ~baseline).astype(np.uint8)
        bg = (baseline & ~current).astype(np.uint8)
    else:
        # No baseline — entire current mask is the foreground scribble.
        fg = current.copy()
        bg = np.zeros(tuple(shape), dtype=np.uint8)

    return (
        fg.tobytes(order="C"),
        bg.tobytes(order="C"),
        int(np.count_nonzero(fg)),
        int(np.count_nonzero(bg)),
    )


def initialize_baselines(runtime_path):
    """Persist current managed-mask buffers as nnInteractive diff baselines."""
    runtime = load_json(runtime_path)
    review_id = runtime.get("review_id", "")
    case_root = runtime.get("package_root", "")
    initialized = 0
    refreshed = 0
    for mask in managed_masks(mimics, review_id):
        target_id = metadata_get(mask, "sp.target_id", "")
        organ = metadata_get(mask, "sp.organ", "")
        if not target_id or not organ:
            continue
        path = _baseline_path(case_root, target_id, organ)
        existed = os.path.isfile(path)
        export_result = export_mask_u8(mask, path)
        if existed:
            refreshed += 1
        else:
            initialized += 1
        metadata_set(mask, "sp.nninteractive_baseline_shape", "x".join(str(v) for v in export_result.get("mimics_shape", [])))
    return {"initialized": initialized, "refreshed": refreshed}


def _choose_changed_candidate(candidates):
    """Choose the edited mask. Ask only when more than one mask changed."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    buttons = []
    lookup = {}
    for index, candidate in enumerate(candidates[:8], start=1):
        label = "{0}. {1}/{2}".format(index, candidate["target_id"], candidate["organ"])
        buttons.append(label)
        lookup[label] = candidate
    buttons.append("Cancel")
    answer = mimics.dialogs.question_box(
        message=(
            "More than one Mask changed since the last AI baseline.\n\n"
            "Choose which organ to refine now. Run AI Refine again for another organ."
        ),
        buttons=";".join(buttons),
        title="AI Refine",
        ui_blocking=True,
    )
    return lookup.get(answer)


def _changed_mask_candidates(runtime, case_root, temp_dir):
    """Return masks with edits since their saved baseline."""
    review_id = runtime.get("review_id", "")
    candidates = []
    initialized_missing_baseline = 0
    for mask in managed_masks(mimics, review_id):
        target_id = metadata_get(mask, "sp.target_id", "")
        organ = metadata_get(mask, "sp.organ", "")
        image_id = metadata_get(mask, "sp.image_id", "")
        if not target_id or not organ or not image_id:
            continue

        current_path = os.path.join(
            temp_dir, "{0}_{1}_current_{2}.u8".format(target_id, organ, uuid.uuid4().hex[:8]),
        )
        export_result = export_mask_u8(mask, current_path)
        actual_shape = export_result.get("mimics_shape", [])
        current_bytes = open(current_path, "rb").read()
        baseline_bytes = _load_baseline_data(case_root, target_id, organ, actual_shape)
        if baseline_bytes is None:
            _save_baseline(mask, case_root, target_id, organ)
            initialized_missing_baseline += 1
            try:
                os.remove(current_path)
            except OSError:
                pass
            continue

        fg_bytes, bg_bytes, fg_count, bg_count = _compute_diff(
            current_bytes, baseline_bytes, actual_shape,
        )
        if fg_count == 0 and bg_count == 0:
            try:
                os.remove(current_path)
            except OSError:
                pass
            continue

        candidates.append(
            {
                "mask": mask,
                "target_id": target_id,
                "organ": organ,
                "image_id": image_id,
                "actual_shape": actual_shape,
                "current_path": current_path,
                "fg_bytes": fg_bytes,
                "bg_bytes": bg_bytes,
                "fg_count": fg_count,
                "bg_count": bg_count,
            }
        )
    return candidates, initialized_missing_baseline


def _image_buffer_dtype(view):
    fmt = getattr(view, "format", "")
    if fmt in ("h", "<h", "=h"):
        return "int16"
    if fmt in ("H", "<H", "=H"):
        return "uint16"
    return "int16"


def _export_image_buffer(image, temp_dir, image_id):
    """Export a Mimics image buffer for the external nnInteractive bridge."""
    path = os.path.join(temp_dir, "{0}_image_i16_{1}.raw".format(image_id, uuid.uuid4().hex[:8]))
    view = image.get_voxel_buffer()
    raw = view.tobytes()
    with open(path, "wb") as handle:
        handle.write(raw)
    return {
        "image_buffer_path": path,
        "image_buffer_shape": [int(value) for value in view.shape],
        "image_buffer_dtype": _image_buffer_dtype(view),
        "image_buffer_coordinates": "mimics",
    }


def _platform_image_path(image_entry):
    path = image_entry.get("image_path")
    if not path:
        return None
    lower = path.lower()
    if not lower.endswith((".nii", ".nii.gz", ".mha", ".mhd")):
        return None
    if not os.path.isfile(path):
        return None
    return path


# ---------------------------------------------------------------------------
#  Refinement execution
# ---------------------------------------------------------------------------

def run_refine(runtime_path):
    """Run nnInteractive refinement using diff-based interaction detection.

    Automatically determines:
      - Which mask to refine (changed-mask detection)
      - Foreground (new paint) vs background (erased) scribbles
      - Always uses scribble mode (covers all practical cases)

    Parameters
    ----------
    runtime_path : str
        Path to mimics_runtime.json

    Returns
    -------
    int
        0 on success, non-zero on error
    """
    runtime = load_json(runtime_path)
    case_root = runtime.get("package_root", "")

    temp_dir = os.path.join(case_root, "working", "nninteractive")
    if not os.path.isdir(temp_dir):
        os.makedirs(temp_dir)

    # 1. Detect which managed Mask changed since its AI baseline.
    candidates, initialized_missing = _changed_mask_candidates(runtime, case_root, temp_dir)
    selected = _choose_changed_candidate(candidates)
    for candidate in candidates:
        if candidate is not selected:
            try:
                os.remove(candidate["current_path"])
            except OSError:
                pass
    if selected is None:
        if initialized_missing:
            return 0, {
                "status": "skipped",
                "reason": "baseline_initialized",
                "initialized": initialized_missing,
            }, 0, 0
        return 0, {"status": "skipped", "reason": "no_changed_mask"}, 0, 0

    target_id = selected["target_id"]
    organ = selected["organ"]
    image_id = selected["image_id"]
    mask = selected["mask"]
    actual_shape = selected["actual_shape"]
    current_path = selected["current_path"]
    fg_bytes = selected["fg_bytes"]
    bg_bytes = selected["bg_bytes"]
    fg_count = selected["fg_count"]
    bg_count = selected["bg_count"]

    # 3. Get buffer mapping and image info.
    mapping_by_image = runtime.get("buffer_mapping_by_image_id", {})
    buffer_mapping = mapping_by_image.get(image_id, runtime.get("buffer_mapping", {}))
    if not buffer_mapping:
        buffer_mapping = {
            "platform_to_mimics_axes": [0, 1, 2],
            "platform_to_mimics_flips": [False, False, False],
        }

    image_entry = None
    for img in runtime.get("image_sets", []):
        if img.get("image_id") == image_id:
            image_entry = img
            break
    if image_entry is None:
        raise RuntimeError("Image {0} not found in runtime".format(image_id))

    image_path = _platform_image_path(image_entry)
    image_buffer_input = {}
    if image_path is None:
        image_map = match_images(mimics, runtime["image_sets"])
        if image_id not in image_map:
            raise RuntimeError("Image {0} is not open in Mimics".format(image_id))
        image_buffer_input = _export_image_buffer(image_map[image_id], temp_dir, image_id)

    # 7. Write interaction buffers.
    call_id = uuid.uuid4().hex[:8]
    fg_path = os.path.join(temp_dir, "{0}_{1}_fg_{2}.u8".format(target_id, organ, call_id))
    bg_path = os.path.join(temp_dir, "{0}_{1}_bg_{2}.u8".format(target_id, organ, call_id))
    output_path = os.path.join(temp_dir, "{0}_{1}_refined_{2}.u8".format(target_id, organ, call_id))

    with open(fg_path, "wb") as f:
        f.write(fg_bytes)
    if bg_count > 0:
        with open(bg_path, "wb") as f:
            f.write(bg_bytes)

    # 8. Call the bridge with both fg and bg in one session.
    python_exe = _find_nninteractive_python()
    bridge_script = _find_bridge_script()
    model_dir = _find_model_dir()
    device = os.environ.get("SP_NNINTERACTIVE_DEVICE", "cuda:0")
    timeout = int(os.environ.get("SP_NNINTERACTIVE_TIMEOUT", "300"))

    # Auto-save a recovery checkpoint before refine (safety net).
    try:
        import sp_save_checkpoint
        sp_save_checkpoint.main(1)  # Keep 1 backup — lightweight.
    except Exception:
        pass  # Best-effort.

    bridge_input = {
        "interaction_path": fg_path,
        "interaction_shape": list(actual_shape),
        "interaction_type": "scribble",
        "include_interaction": True,  # Positive = foreground.
        "buffer_mapping": buffer_mapping,
        "output_path": output_path,
        "model_dir": model_dir,
        "device": device,
    }
    if image_path:
        bridge_input["image_path"] = image_path
    bridge_input.update(image_buffer_input)
    if bg_count > 0:
        bridge_input["bg_interaction_path"] = bg_path

    try:
        proc = subprocess.Popen(
            [python_exe, bridge_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = proc.communicate(
            input=json.dumps(bridge_input).encode("utf-8"),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("nnInteractive bridge timed out after {0}s".format(timeout))

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", "replace") if stderr else ""
        raise RuntimeError(
            "Bridge failed (exit {0}):\n{1}".format(proc.returncode, stderr_text)
        )

    try:
        result = json.loads(stdout.decode("utf-8"))
    except ValueError:
        raise RuntimeError("Bridge returned invalid JSON")

    if result.get("status") == "error":
        raise RuntimeError("Refine error: {0}".format(result.get("error", "unknown")))
    if result.get("status") == "skipped":
        return 0

    # 9. Import refined mask into Mimics.
    if not os.path.isfile(output_path):
        raise RuntimeError("Bridge did not produce output: {0}".format(output_path))

    set_mask_buffer_from_u8(mask, output_path, actual_shape)

    # 11. Save new baseline.
    _save_baseline(mask, case_root, target_id, organ)

    # 12. Clean up temp files.
    cleanup_paths = [current_path, fg_path, bg_path, output_path]
    if image_buffer_input.get("image_buffer_path"):
        cleanup_paths.append(image_buffer_input["image_buffer_path"])
    for p in cleanup_paths:
        try:
            os.remove(p)
        except OSError:
            pass

    return 0, result, fg_count, bg_count


# ---------------------------------------------------------------------------
#  MIMICS GUI entry point
# ---------------------------------------------------------------------------

def main(runtime_path=None):
    """Entry point called from the MIMICS Review Console.

    Zero-dialog interface: detects changed managed masks, computes diffs,
    and refines the segmentation. Shows only a processing message and result.
    """
    if runtime_path is None:
        for mask in managed_masks(mimics):
            package_root = metadata_get(mask, "sp.package_root", "")
            if package_root:
                candidate = os.path.join(
                    package_root, "working", "mimics_runtime.json"
                )
                if os.path.isfile(candidate):
                    runtime_path = candidate
                    break
        if runtime_path is None:
            mimics.dialogs.message_box(
                "No SegmentationPlatform case is open in this MIMICS session.\n\n"
                "Open a case first: Start Labeling → Open Case.",
                title="AI Refine",
                ui_blocking=True,
            )
            return 1

    # Show a brief processing message.
    mimics.dialogs.message_box(
        "AI is refining the segmentation...\n\n"
        "First use in this session: 10-30 seconds\n"
        "(loading the AI model into GPU memory).\n"
        "After that: 1-5 seconds per refine.\n\n"
        "Click OK to start. Mimics will be busy until complete.",
        title="AI Refine — Processing",
        ui_blocking=True,
    )

    try:
        result = run_refine(runtime_path)
        if isinstance(result, tuple):
            returncode, bridge_result, fg_count, bg_count = result
        else:
            returncode = result
            bridge_result = {}
            fg_count = bg_count = 0
    except Exception as error:
        mimics.dialogs.message_box(
            "AI refine failed:\n\n{0}\n\n"
            "Make sure the nnInteractive environment is set up.\n"
            "First-time setup: python scripts/setup_nninteractive_env.py".format(
                str(error)
            ),
            title="AI Refine — Error",
            ui_blocking=True,
        )
        return 2

    if returncode == 0:
        if bridge_result.get("status") == "skipped":
            reason = bridge_result.get("reason", "")
            if reason == "baseline_initialized":
                message = (
                    "AI refine is ready for this case.\n\n"
                    "Paint or erase a small area on one target Mask, then run AI Refine again."
                )
            else:
                message = (
                    "No new Mask edits were detected.\n\n"
                    "Paint or erase a small area on one target Mask, then run AI Refine."
                )
            mimics.dialogs.message_box(
                message,
                title="AI Refine",
                ui_blocking=True,
            )
            return 0

        elapsed = bridge_result.get("elapsed_seconds", 0)
        first_call = bridge_result.get("first_call", False)

        parts = [
            "AI refine complete.",
            "Time: {0:.1f}s".format(elapsed) if elapsed else "",
        ]
        if fg_count:
            parts.append("Foreground scribble: {0} voxels".format(fg_count))
        if bg_count:
            parts.append("Background scribble: {0} voxels".format(bg_count))
        if first_call:
            parts.append("(First call — model was loaded)")

        mimics.dialogs.message_box(
            "\n".join(p for p in parts if p),
            title="AI Refine — Done",
            ui_blocking=True,
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        try:
            mimics.dialogs.message_box(
                "AI refine crashed:\n\n{0}".format(str(error)),
                title="AI Refine — Fatal Error",
                ui_blocking=True,
            )
        finally:
            raise
