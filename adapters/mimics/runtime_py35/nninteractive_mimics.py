# -*- coding: utf-8 -*-
"""Standalone nnInteractive tool for Mimics Research 21.

This module runs inside Mimics Python 3.5. It intentionally has no dependency
on SegmentationPlatform cases, reviews, registries, or runtime manifests.

The user selects a target Mask in the Project Tree and launches the
``nnInteractive`` Scripting Library entry. Prompts are collected with Mimics
native APIs and inference runs in an external Python 3.10+ environment.
"""

from __future__ import print_function

import json
import os
import shutil
import subprocess
import tempfile
import uuid

import mimics


TITLE = "nnInteractive Segmentation"
BUTTON_POINT = "Point"
BUTTON_SCRIBBLE = "Scribble"
BUTTON_BOX = "Box"
BUTTON_LASSO = "Lasso"
BUTTON_UNDO = "Undo Last Prompt"
BUTTON_RESET = "Reset To Start"
BUTTON_FINISH = "Finish"
BUTTON_FOREGROUND = "Foreground"
BUTTON_BACKGROUND = "Background"
BUTTON_CREATE = "Create New Result Mask"
BUTTON_CANCEL = "Cancel"

PROMPT_MASK_PREFIX = "nnInteractive Prompt"
DEFAULT_RESULT_NAME = "nnInteractive Result"


def _find_root(start_dir, sentinel_files, max_depth=6):
    """Walk upward from *start_dir* until a directory containing one of the
    *sentinel_files* is found.

    In the repo layout the root contains ``nninteractive_config.json``.  In an
    exported worklist the root contains ``worklist_manifest.json``.  A bundle
    is detected by the presence of ``nninteractive_env``.
    """
    current = os.path.abspath(start_dir)
    for _ in range(max_depth):
        for sentinel in sentinel_files:
            if os.path.isfile(os.path.join(current, sentinel)):
                return current
            if os.path.isdir(os.path.join(current, sentinel)):
                return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    # Fallback: nninteractive_mimics.py is at <root>/runtime_py35/ so two dirname
    # hops reach the parent of runtime_py35, which is the root in both the worklist
    # and bundle layouts.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _project_root():
    return _find_root(
        os.path.dirname(os.path.abspath(__file__)),
        ("worklist_manifest.json", "nninteractive_config.json", "nninteractive_env", ".git"),
    )


def _integration_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _environment_root():
    # The environment may be inside the worklist, beside it, under the project
    # root, or be the standalone bundle root itself.
    root = _project_root()
    candidates = [
        os.path.join(root, "nninteractive_env"),
        os.path.join(os.path.dirname(root), "nninteractive_env"),
        root,
    ]
    for candidate in candidates:
        if (
            os.path.isfile(os.path.join(candidate, "python", "python.exe"))
            or os.path.isfile(os.path.join(candidate, "Scripts", "python.exe"))
        ):
            return candidate
    return candidates[0]


def _load_json(path):
    with open(path, "r") as handle:
        return json.load(handle)


def _config():
    path = os.environ.get("NNINTERACTIVE_CONFIG", "")
    candidates = [
        path,
        os.path.join(_integration_root(), "nninteractive_config.json"),
        os.path.join(_project_root(), "nninteractive_config.json"),
    ]
    path = next((item for item in candidates if item and os.path.isfile(item)), candidates[-1])
    value = _load_json(path) if os.path.isfile(path) else {}
    value["_config_path"] = path
    return value


def _first_existing_file(candidates, description):
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    checked = [str(item) for item in candidates if item]
    raise RuntimeError("{0} not found. Checked:\n{1}".format(description, "\n".join(checked)))


def _first_existing_dir(candidates, description):
    for candidate in candidates:
        if candidate and os.path.isdir(candidate):
            return candidate
    checked = [str(item) for item in candidates if item]
    raise RuntimeError("{0} not found. Checked:\n{1}".format(description, "\n".join(checked)))


def _runtime_paths(config):
    root = _project_root()
    integration_root = _integration_root()
    environment_root = _environment_root()
    python_exe = _first_existing_file(
        [
            os.environ.get("NNINTERACTIVE_PYTHON", ""),
            config.get("python", ""),
            os.path.join(environment_root, "python", "python.exe"),
            os.path.join(root, "nninteractive_env", "Scripts", "python.exe"),
            os.path.join(root, "nninteractive_env", "python", "python.exe"),
        ],
        "nnInteractive Python",
    )
    bridge_script = _first_existing_file(
        [
            os.environ.get("NNINTERACTIVE_BRIDGE", ""),
            config.get("bridge_script", ""),
            os.path.join(integration_root, "nninteractive_bridge.py"),
            os.path.join(integration_root, "bridge", "nninteractive_bridge.py"),
        ],
        "nnInteractive bridge script",
    )
    model_dir = _first_existing_dir(
        [
            os.environ.get("NNINTERACTIVE_MODEL_DIR", ""),
            config.get("model_dir", ""),
            os.path.join(environment_root, "models", "nnInteractive_v1.0"),
            os.path.join(root, "nninteractive_env", "models", "nnInteractive_v1.0"),
        ],
        "nnInteractive model directory",
    )
    return python_exe, bridge_script, model_dir


def _same_object(left, right):
    if left is right:
        return True
    return bool(
        left is not None
        and right is not None
        and getattr(left, "guid", None)
        and getattr(left, "guid", None) == getattr(right, "guid", None)
    )


def _mask_is_prompt(mask):
    return str(getattr(mask, "name", "")).startswith(PROMPT_MASK_PREFIX)


def _masks_for_image(image):
    result = []
    for mask in mimics.data.masks:
        if _mask_is_prompt(mask):
            continue
        mask_image = getattr(mask, "image", None)
        if mask_image is None or _same_object(mask_image, image):
            result.append(mask)
    return result


def _unique_result_name():
    existing = set(str(getattr(mask, "name", "")) for mask in mimics.data.masks)
    if DEFAULT_RESULT_NAME not in existing:
        return DEFAULT_RESULT_NAME
    index = 2
    while "{0} {1}".format(DEFAULT_RESULT_NAME, index) in existing:
        index += 1
    return "{0} {1}".format(DEFAULT_RESULT_NAME, index)


def _create_result_mask(image):
    mask = mimics.segment.create_mask()
    mask.name = _unique_result_name()
    try:
        mask.image = image
    except Exception as error:
        try:
            mimics.data.masks.delete(mask)
        except Exception:
            pass
        raise RuntimeError("Could not bind the new result Mask to the active image: {0}".format(error))
    mask.visible = True
    mask.selected = True
    return mask


def _select_target_mask(image):
    selected = [mask for mask in _masks_for_image(image) if bool(getattr(mask, "selected", False))]
    if len(selected) == 1:
        target = selected[0]
    elif len(selected) > 1:
        raise RuntimeError(
            "Select exactly one target Mask in the Project Tree, then run nnInteractive again."
        )
    else:
        answer = mimics.dialogs.question_box(
            message=(
                "No target Mask is selected.\n\n"
                "Select an existing Mask in the Project Tree, or create a new empty result Mask."
            ),
            buttons=BUTTON_CREATE + ";" + BUTTON_CANCEL,
            title=TITLE,
            ui_blocking=True,
        )
        if answer != BUTTON_CREATE:
            return None
        target = _create_result_mask(image)

    target_image = getattr(target, "image", None)
    if target_image is None:
        try:
            target.image = image
        except Exception as error:
            raise RuntimeError("The target Mask is not bound to the active image: {0}".format(error))
    elif not _same_object(target_image, image):
        raise RuntimeError(
            "The selected Mask belongs to a different image set. "
            "Activate its image set or select another Mask."
        )
    return target


def _buffer_dtype(view):
    fmt = str(getattr(view, "format", ""))
    if fmt in ("b", "<b", "=b"):
        return "int8"
    if fmt in ("B", "<B", "=B"):
        return "uint8"
    if fmt in ("h", "<h", "=h"):
        return "int16"
    if fmt in ("H", "<H", "=H"):
        return "uint16"
    if fmt in ("i", "<i", "=i"):
        return "int32"
    if fmt in ("I", "<I", "=I"):
        return "uint32"
    if fmt in ("f", "<f", "=f"):
        return "float32"
    raise RuntimeError(
        "Unsupported Mimics image buffer format {0!r}. "
        "Do not guess the voxel dtype; record this format during workstation validation.".format(fmt)
    )


def _export_image(image, path):
    view = image.get_voxel_buffer()
    with open(path, "wb") as handle:
        handle.write(view.tobytes())
    return {
        "path": path,
        "shape": [int(value) for value in view.shape],
        "dtype": _buffer_dtype(view),
    }


def _export_mask(mask, path):
    view = mask.get_voxel_buffer()
    raw = view.tobytes()
    with open(path, "wb") as handle:
        handle.write(raw)
    return {
        "path": path,
        "shape": [int(value) for value in view.shape],
        "pixel_count": int(getattr(mask, "number_of_pixels", 0)),
        "byte_count": len(raw),
    }


def _set_mask_from_u8(mask, path, shape):
    raw = open(path, "rb").read()
    expected = int(shape[0]) * int(shape[1]) * int(shape[2])
    if len(raw) != expected:
        raise RuntimeError("Prediction byte count mismatch: {0} != {1}".format(len(raw), expected))
    try:
        import numpy as np

        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(tuple(shape)).astype(np.bool_)
        mask.set_voxel_buffer(pixels)
    except ImportError:
        pixels = memoryview(bytearray(raw)).cast("?", shape=list(shape))
        mask.set_voxel_buffer(pixels)


def _restore_base(mask, base_path, base_shape):
    _set_mask_from_u8(mask, base_path, base_shape)


def _choose_sign():
    answer = mimics.dialogs.question_box(
        message=(
            "Foreground means the structure should be included.\n"
            "Background means the structure should be excluded."
        ),
        buttons=BUTTON_FOREGROUND + ";" + BUTTON_BACKGROUND + ";" + BUTTON_CANCEL,
        title=TITLE,
        ui_blocking=True,
    )
    if answer == BUTTON_FOREGROUND:
        return True
    if answer == BUTTON_BACKGROUND:
        return False
    return None


def _capture_point(image, include):
    try:
        coordinates = mimics.indicate_coordinate(
            message=(
                "Click inside the structure."
                if include
                else "Click an area that must be excluded from the structure."
            ),
            show_message_box=True,
            confirm=True,
            title=TITLE,
        )
    except mimics.UserInterrupted:
        return None
    indexes = image.get_voxel_indexes(coordinates)
    return {
        "interaction_type": "point",
        "include_interaction": bool(include),
        "point": [int(value) for value in indexes],
        "coordinates": "mimics",
    }


def _point_coordinates(value):
    if hasattr(value, "coordinates"):
        value = value.coordinates
    return tuple(float(item) for item in value)


def _spline_geometry(spline):
    geometry = getattr(spline, "geometry_points", None)
    if not geometry:
        geometry = getattr(spline, "points", None)
    if not geometry:
        raise RuntimeError(
            "Mimics returned a Spline without geometry_points or points. "
            "The Scribble prompt cannot be converted to voxel coordinates."
        )
    return list(geometry)


def _capture_scribble(image, include):
    spline = None
    try:
        spline = mimics.analyze.indicate_spline(
            message=(
                "Draw a foreground scribble through the structure."
                if include
                else "Draw a background scribble over an incorrect region."
            ),
            show_message_box=True,
            confirm=True,
            title=TITLE,
        )
        geometry = _spline_geometry(spline)
        points = []
        for point in geometry:
            indexes = image.get_voxel_indexes(_point_coordinates(point))
            current = [int(value) for value in indexes]
            if not points or current != points[-1]:
                points.append(current)
        if len(points) < 2:
            raise RuntimeError(
                "The Scribble contains fewer than two distinct voxel points. "
                "Draw a longer curve and try again."
            )
        return {
            "interaction_type": "scribble",
            "include_interaction": bool(include),
            "polyline_points": points,
            "coordinates": "mimics",
        }
    except mimics.UserInterrupted:
        return None
    finally:
        if spline is not None:
            try:
                mimics.data.splines.delete(spline)
            except Exception:
                pass


def _create_prompt_mask(image, include, interaction_type):
    mask = mimics.segment.create_mask()
    try:
        mask.name = "{0} {1} {2}".format(
            PROMPT_MASK_PREFIX,
            "Foreground" if include else "Background",
            interaction_type,
        )
        mask.image = image
        mask.visible = True
        mask.color = (0.1, 1.0, 0.2) if include else (1.0, 0.2, 0.1)
        return mask
    except Exception:
        try:
            mimics.data.masks.delete(mask)
        except Exception:
            pass
        raise


def _capture_region_prompt(image, include, interaction_type, edit_type, temp_dir):
    prompt_mask = _create_prompt_mask(image, include, interaction_type)
    try:
        mimics.segment.activate_edit_mask(prompt_mask, edit_type, "Draw")
        if int(getattr(prompt_mask, "number_of_pixels", 0)) <= 0:
            return None
        view = prompt_mask.get_voxel_buffer()
        full_shape = [int(value) for value in view.shape]
        try:
            import numpy as np

            prompt = np.asarray(view, dtype=np.uint8)
            nonzero = np.argwhere(prompt)
            if len(nonzero) == 0:
                return None
            minimum = nonzero.min(axis=0)
            maximum = nonzero.max(axis=0) + 1
            bbox = [
                [int(minimum[axis]), int(maximum[axis])]
                for axis in range(3)
            ]
            if interaction_type == "box":
                return {
                    "interaction_type": interaction_type,
                    "include_interaction": bool(include),
                    "bbox": bbox,
                    "full_shape": full_shape,
                    "coordinates": "mimics",
                }
            crop = prompt[
                bbox[0][0]:bbox[0][1],
                bbox[1][0]:bbox[1][1],
                bbox[2][0]:bbox[2][1],
            ]
            path = os.path.join(
                temp_dir,
                "prompt_{0}_{1}.u8".format(interaction_type, uuid.uuid4().hex),
            )
            with open(path, "wb") as handle:
                handle.write(crop.tobytes(order="C"))
            return {
                "interaction_type": interaction_type,
                "include_interaction": bool(include),
                "mask_path": path,
                "mask_shape": [int(value) for value in crop.shape],
                "interaction_bbox": bbox,
                "full_shape": full_shape,
                "coordinates": "mimics",
            }
        except ImportError:
            pass

        path = os.path.join(
            temp_dir,
            "prompt_{0}_{1}.u8".format(interaction_type, uuid.uuid4().hex),
        )
        exported = _export_mask(prompt_mask, path)
        return {
            "interaction_type": interaction_type,
            "include_interaction": bool(include),
            "mask_path": path,
            "mask_shape": exported["shape"],
            "full_shape": exported["shape"],
            "coordinates": "mimics",
        }
    except mimics.UserInterrupted:
        return None
    finally:
        try:
            mimics.data.masks.delete(prompt_mask)
        except Exception:
            pass


def _capture_prompt(kind, image, include, temp_dir):
    if kind == BUTTON_POINT:
        return _capture_point(image, include)
    if kind == BUTTON_SCRIBBLE:
        return _capture_scribble(image, include)
    if kind == BUTTON_BOX:
        return _capture_region_prompt(image, include, "box", "Rectangle", temp_dir)
    if kind == BUTTON_LASSO:
        return _capture_region_prompt(image, include, "lasso", "Lasso", temp_dir)
    raise RuntimeError("Unsupported prompt kind: {0}".format(kind))


def _bridge_call(config, image_export, base_export, interactions, output_path):
    python_exe, bridge_script, model_dir = _runtime_paths(config)
    request = {
        "image_buffer_path": image_export["path"],
        "image_buffer_shape": image_export["shape"],
        "image_buffer_dtype": image_export["dtype"],
        "image_buffer_coordinates": "mimics",
        "buffer_mapping": {
            "platform_to_mimics_axes": [0, 1, 2],
            "platform_to_mimics_flips": [False, False, False],
        },
        "initial_seg_path": base_export["path"] if base_export["pixel_count"] > 0 else None,
        "initial_seg_shape": base_export["shape"],
        "interactions": interactions,
        "output_path": output_path,
        "model_dir": model_dir,
        "device": os.environ.get(
            "NNINTERACTIVE_DEVICE",
            config.get("device", "cuda:0"),
        ),
        "server_url": os.environ.get(
            "NNINTERACTIVE_SERVER_URL",
            config.get("server_url", "http://127.0.0.1:1527"),
        ),
        "auto_start_server": bool(config.get("auto_start_server", True)),
        "server_idle_timeout_seconds": int(
            os.environ.get(
                "NNINTERACTIVE_SERVER_IDLE_TIMEOUT",
                config.get("server_idle_timeout_seconds", 1800),
            )
        ),
    }
    timeout = int(os.environ.get("NNINTERACTIVE_TIMEOUT", config.get("timeout_seconds", 300)))
    process = subprocess.Popen(
        [python_exe, bridge_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        stdout, stderr = process.communicate(
            input=json.dumps(request).encode("utf-8"),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise RuntimeError("nnInteractive timed out after {0} seconds".format(timeout))
    if process.returncode != 0:
        raise RuntimeError(
            "nnInteractive bridge failed:\n{0}".format(
                stderr.decode("utf-8", "replace") if stderr else ""
            )
        )
    try:
        result = json.loads(stdout.decode("utf-8"))
    except ValueError:
        raise RuntimeError("nnInteractive bridge returned invalid JSON")
    if result.get("status") == "error":
        raise RuntimeError(result.get("error", "Unknown nnInteractive error"))
    return result


def _run_prediction(config, image_export, base_export, target, interactions, temp_dir):
    output_path = os.path.join(temp_dir, "prediction.u8")
    result = _bridge_call(config, image_export, base_export, interactions, output_path)
    status = result.get("status")
    if status == "skipped":
        # No actionable interaction (e.g. all-empty prompts on undo replay): roll
        # the mask back to the base instead of treating the non-prediction as error.
        _restore_base(target, base_export["path"], base_export["shape"])
        return result
    if status != "refined":
        raise RuntimeError(
            "nnInteractive did not produce a prediction: {0}".format(result.get("reason", status))
        )
    _set_mask_from_u8(target, output_path, base_export["shape"])
    return result


def _prompt_menu(target, interaction_count):
    return mimics.dialogs.question_box(
        message=(
            "Target Mask: {0}\n"
            "Prompts in this session: {1}\n\n"
            "Each new prompt immediately updates the selected Mask."
        ).format(getattr(target, "name", ""), interaction_count),
        buttons=";".join(
            [
                BUTTON_POINT,
                BUTTON_SCRIBBLE,
                BUTTON_BOX,
                BUTTON_LASSO,
                BUTTON_UNDO,
                BUTTON_RESET,
                BUTTON_FINISH,
            ]
        ),
        title=TITLE,
        ui_blocking=True,
    )


def run():
    image = mimics.data.images.get_active()
    if image is None:
        raise RuntimeError("Open a project and activate an image set before running nnInteractive.")
    target = _select_target_mask(image)
    if target is None:
        return 0

    temp_dir = tempfile.mkdtemp(prefix="mimics_nninteractive_")
    try:
        image_export = _export_image(image, os.path.join(temp_dir, "image.raw"))
        base_export = _export_mask(target, os.path.join(temp_dir, "target_at_start.u8"))
        if image_export["shape"] != base_export["shape"]:
            raise RuntimeError(
                "Image and target Mask buffer shapes differ: {0} vs {1}".format(
                    image_export["shape"], base_export["shape"]
                )
            )

        interactions = []
        config = _config()
        while True:
            action = _prompt_menu(target, len(interactions))
            if action == BUTTON_FINISH or not action:
                return 0
            if action == BUTTON_RESET:
                interactions = []
                _restore_base(target, base_export["path"], base_export["shape"])
                continue
            if action == BUTTON_UNDO:
                if not interactions:
                    continue
                interactions.pop()
                if interactions:
                    try:
                        _run_prediction(
                            config,
                            image_export,
                            base_export,
                            target,
                            interactions,
                            temp_dir,
                        )
                    except Exception:
                        _restore_base(target, base_export["path"], base_export["shape"])
                        raise
                else:
                    _restore_base(target, base_export["path"], base_export["shape"])
                continue

            include = _choose_sign()
            if include is None:
                continue
            prompt = _capture_prompt(action, image, include, temp_dir)
            if prompt is None:
                continue
            interactions.append(prompt)
            try:
                _run_prediction(
                    config,
                    image_export,
                    base_export,
                    target,
                    interactions,
                    temp_dir,
                )
            except Exception:
                interactions.pop()
                raise
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    try:
        return run()
    except Exception as error:
        mimics.dialogs.message_box(
            "nnInteractive could not continue.\n\n{0}".format(str(error)),
            title=TITLE,
            ui_blocking=True,
        )
        return 2


if __name__ == "__main__":
    main()
