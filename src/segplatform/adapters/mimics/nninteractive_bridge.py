# -*- coding: utf-8 -*-
"""nnInteractive bridge for MIMICS segmentation refinement.

This script runs in the nnInteractive virtual environment (Python 3.10+ with
PyTorch). It receives interaction data via JSON stdin, communicates with the
nnInteractive server (auto-launched if needed), and writes the refined mask
as a .u8 buffer.

The bridge auto-manages the nnInteractive server lifecycle:
  - On first call: starts the server as a background subprocess.
  - Subsequent calls: reuse the running server.
  - The server auto-exits after a configurable idle timeout (default 30 min).
  - No manual server management needed by the annotator.

Protocol (JSON stdin -> JSON stdout):
    Input keys:
        image_path          : str   — Optional NIfTI image in platform coordinates
        image_buffer_path   : str   — Optional raw image buffer exported from MIMICS
        image_buffer_shape  : [int, int, int] — Required with image_buffer_path
        image_buffer_dtype  : str   — Optional NumPy dtype, default int16
        interaction_path    : str   — .u8 buffer in MIMICS coordinates (foreground scribble)
        interaction_shape   : [int, int, int] — MIMICS voxel dimensions
        interaction_type    : str   — "scribble" | "box" | "point" | "lasso"
        include_interaction : bool  — True = foreground, False = background
        buffer_mapping      : dict  — { platform_to_mimics_axes, platform_to_mimics_flips }
        output_path         : str   — Where to write the refined .u8 buffer
        model_dir           : str   — Path to nnInteractive checkpoint folder
        [bg_interaction_path] : str — Optional background scribble .u8 buffer
        [server_url]        : str   — Optional existing nnInteractive server URL
        [device]            : str   — "cuda:0" (default), "cpu"

    Output keys:
        status              : str   — "refined" | "skipped" | "error"
        output_path         : str
        elapsed_seconds     : float
        mode                : str   — "remote" | "local"
        first_call          : bool  — True if server was just started (model loading)
        [error]             : str   — Present only when status == "error"
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np


# ---------------------------------------------------------------------------
#  Server lifecycle management
# ---------------------------------------------------------------------------

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 1527
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"
SERVER_STARTUP_TIMEOUT = 120  # seconds to wait for model to load
HEALTHZ_RETRY_INTERVAL = 1.0   # seconds between healthz checks


def _server_pid_path(model_dir: str) -> Path:
    """Path to the PID file for the server process."""
    return Path(model_dir).parent / ".nninteractive_server.pid"


def _server_log_path(model_dir: str) -> Path:
    """Path to the server log file."""
    return Path(model_dir).parent / ".nninteractive_server.log"


def _server_running() -> bool:
    """Check if the nnInteractive server is already running on the default port."""
    import urllib.request
    try:
        req = urllib.request.Request(f"{SERVER_URL}/healthz")
        resp = urllib.request.urlopen(req, timeout=3)
        return resp.status == 200
    except Exception:
        return False


def _start_server(model_dir: str, device: str) -> subprocess.Popen:
    """Start the nnInteractive server as a background subprocess.

    Returns the Popen object. The server processes requests after the model
    is loaded (~10-30 seconds on first start).
    """
    # Use the same Python that's running this bridge (guaranteed to have the
    # nnInteractive package available, whether from venv or portable bundle).
    python_exe = sys.executable
    log_path = _server_log_path(model_dir)
    pid_path = _server_pid_path(model_dir)

    # Build env: ensure site-packages from the portable bundle are on PYTHONPATH.
    env = os.environ.copy()
    bundle_site = os.path.join(os.path.dirname(python_exe), "..", "Lib", "site-packages")
    bundle_site = os.path.normpath(bundle_site)
    if os.path.isdir(bundle_site):
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = bundle_site + (";" + existing if existing else "")

    # If there's a stale PID file, clean it up.
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text().strip())
            try:
                os.kill(old_pid, 0)  # Signal 0 = just check if process exists
            except OSError:
                pass  # Process doesn't exist, clean up below
            else:
                # Process exists but server wasn't reachable. Kill it.
                try:
                    os.kill(old_pid, signal.SIGTERM)
                except OSError:
                    pass
                time.sleep(1)
        except (ValueError, FileNotFoundError):
            pass
        pid_path.unlink(missing_ok=True)

    # Determine the server module entry point.
    # nninteractive-server is registered as a console script entry point.
    # We call it via `python -m nnInteractive.inference.server.main`.
    cmd = [
        python_exe,
        "-m", "nnInteractive.inference.server.main",
        "--model-dir", str(model_dir),
        "--fold", "all",
        "--host", SERVER_HOST,
        "--port", str(SERVER_PORT),
        "--device", device,
        "--idle-timeout-seconds", "1800",  # 30 min idle → auto-shutdown
        "--liveness-timeout-seconds", "120",
        "--max-sessions", "1",
    ]

    with open(log_path, "a") as log_fh:
        log_fh.write(f"\n{'='*60}\n")
        log_fh.write(f"Starting nnInteractive server at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        log_fh.write(f"Command: {' '.join(cmd)}\n")
        log_fh.flush()

        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,  # Detach from parent process group
        )

    # Write PID file.
    pid_path.write_text(str(proc.pid))
    return proc


def _wait_for_server(timeout: float = SERVER_STARTUP_TIMEOUT) -> bool:
    """Block until the server responds to healthz or timeout.

    Returns True if the server is ready.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_running():
            return True
        time.sleep(HEALTHZ_RETRY_INTERVAL)
    return False


def _ensure_server(model_dir: str, device: str) -> tuple[bool, str]:
    """Ensure the nnInteractive server is running; start it if needed.

    Returns (first_call, server_url).
      - first_call=True means the server was just started (model loading).
    """
    if _server_running():
        return False, SERVER_URL

    # Server not running — start it.
    proc = _start_server(model_dir, device)

    # Wait for the server to be ready.
    ready = _wait_for_server()
    if not ready:
        # Server failed to start. Clean up.
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        raise RuntimeError(
            "nnInteractive server failed to start within {0}s. "
            "Check log: {1}".format(SERVER_STARTUP_TIMEOUT, _server_log_path(model_dir))
        )

    return True, SERVER_URL


# ---------------------------------------------------------------------------
#  Buffer mapping (platform <-> MIMICS)
# ---------------------------------------------------------------------------

def _apply_mapping(array: np.ndarray, axes: list[int], flips: list[bool]) -> np.ndarray:
    """Transpose + flip a numpy array according to the buffer mapping."""
    result = np.transpose(array, axes)
    for axis, flip in enumerate(flips):
        if flip:
            result = np.flip(result, axis=axis)
    return result.copy()


def _invert_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Compute the inverse of a buffer mapping."""
    axes: list[int] = list(mapping["platform_to_mimics_axes"])
    flips: list[bool] = list(mapping["platform_to_mimics_flips"])
    inv_axes = [0] * len(axes)
    for i, a in enumerate(axes):
        inv_axes[a] = i
    inv_flips = [flips[inv_axes[i]] for i in range(len(flips))]
    return {"platform_to_mimics_axes": inv_axes, "platform_to_mimics_flips": inv_flips}


def mimics_to_platform(array: np.ndarray, mapping: dict[str, Any]) -> np.ndarray:
    """Transform a MIMICS-coordinate array into platform coordinates."""
    inv = _invert_mapping(mapping)
    return _apply_mapping(array, inv["platform_to_mimics_axes"], inv["platform_to_mimics_flips"])


def platform_to_mimics(array: np.ndarray, mapping: dict[str, Any]) -> np.ndarray:
    """Transform a platform-coordinate array into MIMICS coordinates."""
    return _apply_mapping(
        array,
        list(mapping["platform_to_mimics_axes"]),
        list(mapping["platform_to_mimics_flips"]),
    )


# ---------------------------------------------------------------------------
#  nnInteractive session
# ---------------------------------------------------------------------------

def _connect_remote(server_url: str) -> Any:
    """Connect to a running nnInteractive server."""
    from nnInteractive.inference.remote import nnInteractiveRemoteInferenceSession

    api_key = os.environ.get("NN_INTERACTIVE_API_KEY")
    return nnInteractiveRemoteInferenceSession(
        server_url=server_url,
        api_key=api_key,
    )


def _connect_local(model_dir: str, device: str) -> Any:
    """Load the nnInteractive model locally (in-process)."""
    import torch
    from nnInteractive.inference.inference_session import nnInteractiveInferenceSession

    session = nnInteractiveInferenceSession(
        device=torch.device(device),
        use_torch_compile=False,
        verbose=False,
        torch_n_threads=os.cpu_count() or 4,
        do_autozoom=True,
    )
    session.initialize_from_trained_model_folder(str(model_dir))
    return session


# ---------------------------------------------------------------------------
#  Image loading
# ---------------------------------------------------------------------------

def load_image_nifti(path: str) -> np.ndarray:
    """Load a NIfTI image as a float32 4D array with shape (1, X, Y, Z)."""
    nii = nib.load(path)
    data = np.asarray(nii.dataobj, dtype=np.float32)
    if data.ndim == 3:
        data = data[None]
    elif data.ndim == 4:
        data = data[0:1]
    else:
        raise RuntimeError(f"Unexpected image dimensions: {data.ndim}")
    return data


def load_image_raw(
    path: str,
    shape: list[int],
    dtype: str,
    *,
    buffer_mapping: dict[str, Any],
    coordinates: str = "mimics",
) -> np.ndarray:
    """Load a raw image buffer as a float32 4D platform-coordinate array."""
    raw_dtype = np.dtype(dtype)
    raw = Path(path).read_bytes()
    expected = int(np.prod(shape)) * raw_dtype.itemsize
    if len(raw) != expected:
        raise RuntimeError(
            f"Image buffer byte count mismatch: {len(raw)} != {expected}"
        )
    data = np.frombuffer(raw, dtype=raw_dtype).reshape(tuple(shape))
    if coordinates == "mimics":
        data = mimics_to_platform(data, buffer_mapping)
    elif coordinates != "platform":
        raise RuntimeError(f"Unsupported image buffer coordinates: {coordinates}")
    return data.astype(np.float32, copy=False)[None]


def load_interaction_u8(path: str, shape: list[int]) -> np.ndarray:
    """Load a .u8 buffer as a bool 3D array with the given MIMICS shape."""
    raw = Path(path).read_bytes()
    expected = int(shape[0]) * int(shape[1]) * int(shape[2])
    if len(raw) != expected:
        raise RuntimeError(
            f"Interaction buffer byte count mismatch: {len(raw)} != {expected}"
        )
    return np.frombuffer(raw, dtype=np.uint8).reshape(tuple(shape)).astype(bool)


def _nonzero_bbox(mask: np.ndarray) -> list[list[int]] | None:
    nonzero = np.argwhere(mask)
    if len(nonzero) == 0:
        return None
    mins = nonzero.min(axis=0)
    maxs = nonzero.max(axis=0) + 1
    return [[int(mins[d]), int(maxs[d])] for d in range(3)]


def _iter_2d_interaction_crops(mask: np.ndarray) -> list[tuple[np.ndarray, list[list[int]]]]:
    """Split a sparse 3D edit mask into nnInteractive-compatible 2D crops."""
    if not np.any(mask):
        return []
    candidates: list[tuple[int, np.ndarray]] = []
    for axis in range(3):
        reduce_axes = tuple(i for i in range(3) if i != axis)
        indices = np.where(mask.any(axis=reduce_axes))[0]
        if len(indices):
            candidates.append((axis, indices))
    if not candidates:
        return []

    axis, indices = min(candidates, key=lambda item: len(item[1]))
    result: list[tuple[np.ndarray, list[list[int]]]] = []
    for index in indices:
        selector = [slice(None), slice(None), slice(None)]
        selector[axis] = slice(int(index), int(index) + 1)
        slice_mask = mask[tuple(selector)]
        local_bbox = _nonzero_bbox(slice_mask)
        if local_bbox is None:
            continue

        bbox = [list(item) for item in local_bbox]
        bbox[axis] = [int(index), int(index) + 1]
        crop = mask[
            bbox[0][0]:bbox[0][1],
            bbox[1][0]:bbox[1][1],
            bbox[2][0]:bbox[2][1],
        ].astype(np.uint8)
        result.append((crop, bbox))
    return result


# ---------------------------------------------------------------------------
#  Main bridge entry point
# ---------------------------------------------------------------------------

def run_bridge(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute nnInteractive refinement.

    Auto-manages server lifecycle: starts server on first call, reuses it
    for subsequent calls. The server auto-terminates after idle timeout.

    Parameters
    ----------
    input_data : dict
        See module docstring for the full protocol.

    Returns
    -------
    dict
        { status, output_path, elapsed_seconds, mode, first_call, [error] }
    """
    started = time.time()

    # --- Validate required keys ---
    required = ["interaction_path", "interaction_shape", "interaction_type", "output_path", "model_dir"]
    missing = [k for k in required if k not in input_data]
    if missing:
        return {"status": "error", "error": f"Missing required keys: {missing}"}

    image_path: str | None = input_data.get("image_path")
    interaction_path: str = input_data["interaction_path"]
    interaction_shape: list[int] = input_data["interaction_shape"]
    interaction_type: str = input_data["interaction_type"]
    include_interaction: bool = input_data.get("include_interaction", True)
    output_path: str = input_data["output_path"]
    model_dir: str = input_data["model_dir"]
    device: str = input_data.get("device", "cuda:0")
    buffer_mapping: dict[str, Any] = input_data.get("buffer_mapping", {})

    if not buffer_mapping:
        buffer_mapping = {
            "platform_to_mimics_axes": [0, 1, 2],
            "platform_to_mimics_flips": [False, False, False],
        }

    try:
        # --- Load image ---
        if input_data.get("image_buffer_path"):
            image_np = load_image_raw(
                input_data["image_buffer_path"],
                input_data["image_buffer_shape"],
                input_data.get("image_buffer_dtype", "int16"),
                buffer_mapping=buffer_mapping,
                coordinates=input_data.get("image_buffer_coordinates", "mimics"),
            )
        elif image_path:
            image_np = load_image_nifti(image_path)
        else:
            return {"status": "error", "error": "Missing image_path or image_buffer_path"}

        # --- Load interaction mask (MIMICS coordinates) ---
        interaction_mimics = load_interaction_u8(interaction_path, interaction_shape)

        # --- Map interaction to platform coordinates ---
        interaction_platform = mimics_to_platform(interaction_mimics, buffer_mapping)

        # --- Validate interaction has content ---
        if not np.any(interaction_platform):
            return {
                "status": "skipped",
                "output_path": output_path,
                "elapsed_seconds": round(time.time() - started, 2),
                "reason": "interaction_mask_empty",
            }

        # --- Auto-manage server: start if needed ---
        server_url = input_data.get("server_url") or SERVER_URL
        auto_start = bool(input_data.get("auto_start_server", True))
        if auto_start and server_url == SERVER_URL:
            first_call, server_url = _ensure_server(model_dir, device)
        else:
            first_call = False

        # --- Connect to server ---
        session = _connect_remote(server_url)
        mode = "remote"

        try:
            session.set_image(image_np)

            target = np.zeros(image_np.shape[1:], dtype=np.uint8)
            session.set_target_buffer(target)

            # --- Helper: apply a single interaction ---
            def _apply_one(interaction_mask, incl):
                if interaction_type == "scribble":
                    for crop, bbox in _iter_2d_interaction_crops(interaction_mask):
                        session.add_scribble_interaction(
                            crop,
                            include_interaction=incl,
                            interaction_bbox=bbox,
                        )
                elif interaction_type == "box":
                    bbox = _nonzero_bbox(interaction_mask)
                    if bbox is not None:
                        session.add_bbox_interaction(bbox, include_interaction=incl)
                elif interaction_type == "point":
                    nonzero = np.argwhere(interaction_mask)
                    if len(nonzero) > 0:
                        center = tuple(int(c) for c in nonzero.mean(axis=0).round())
                        session.add_point_interaction(center, include_interaction=incl)
                elif interaction_type == "lasso":
                    for crop, bbox in _iter_2d_interaction_crops(interaction_mask):
                        session.add_lasso_interaction(
                            crop,
                            include_interaction=incl,
                            interaction_bbox=bbox,
                        )
                else:
                    raise RuntimeError(f"Unsupported interaction_type: {interaction_type}")

            # --- Apply foreground (positive) interaction ---
            _apply_one(interaction_platform, include_interaction)

            # --- Apply background (negative) interaction if provided ---
            bg_interaction_path: str | None = input_data.get("bg_interaction_path")
            if bg_interaction_path:
                bg_mimics = load_interaction_u8(bg_interaction_path, interaction_shape)
                bg_platform = mimics_to_platform(bg_mimics, buffer_mapping)
                if np.any(bg_platform):
                    _apply_one(bg_platform, False)  # False = background / negative

            # --- Get result ---
            result_platform = np.asarray(target, dtype=np.uint8)

            # --- Map result to MIMICS coordinates ---
            result_mimics = platform_to_mimics(result_platform, buffer_mapping)

            # --- Write output .u8 buffer ---
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(result_mimics.tobytes(order="C"))

        finally:
            try:
                session.close()
            except Exception:
                pass

        elapsed = time.time() - started
        return {
            "status": "refined",
            "output_path": output_path,
            "elapsed_seconds": round(elapsed, 2),
            "mode": mode,
            "first_call": first_call,
            "result_shape": list(result_mimics.shape),
            "foreground_voxels": int(np.count_nonzero(result_mimics)),
        }

    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "elapsed_seconds": round(time.time() - started, 2),
        }


def main() -> int:
    """CLI entry point: reads JSON from stdin, writes JSON to stdout."""
    try:
        raw = sys.stdin.read()
        input_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "error": f"Invalid JSON input: {exc}"}
        print(json.dumps(result, indent=2))
        return 2

    result = run_bridge(input_data)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] != "error" else 2


if __name__ == "__main__":
    sys.exit(main())
