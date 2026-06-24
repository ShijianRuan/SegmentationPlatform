# -*- coding: utf-8 -*-
"""Standalone nnInteractive bridge for Mimics segmentation.

This script runs in the nnInteractive virtual environment (Python 3.10+ with
PyTorch). It receives interaction data via JSON stdin, communicates with the
nnInteractive server (auto-launched if needed), and writes the refined mask
as a .u8 buffer.

The bridge auto-manages the nnInteractive server lifecycle:
  - On first call: starts the server as a background subprocess.
  - Subsequent calls: reuse the running server.
  - An owned watchdog stops the service after a configurable idle timeout.
  - No manual server management needed by the annotator.

Protocol (JSON stdin -> JSON stdout):
    Input keys:
        image_path          : str   — Optional NIfTI image in platform coordinates
        image_buffer_path   : str   — Optional raw image buffer exported from MIMICS
        image_buffer_shape  : [int, int, int] — Required with image_buffer_path
        image_buffer_dtype  : str   — Optional NumPy dtype, default int16
        interactions        : list  — Ordered point/scribble/box/lasso prompts
        [initial_seg_path]  : str   — Optional starting Mask in MIMICS coordinates
        [initial_seg_shape] : [int, int, int]
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
import uuid
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
SERVER_IDLE_TIMEOUT = 1800


def _server_state_path(model_dir: str) -> Path:
    """Path to the owned-server state file."""
    return Path(model_dir).parent / ".nninteractive_server.json"


def _server_log_path(model_dir: str) -> Path:
    """Path to the server log file."""
    return Path(model_dir).parent / ".nninteractive_server.log"


def _write_server_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _load_server_state(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _process_command_line(pid: int) -> str | None:
    try:
        if os.name == "nt":
            command = [
                "powershell",
                "-NoProfile",
                "-Command",
                (
                    "(Get-CimInstance Win32_Process -Filter "
                    "\"ProcessId = {0}\").CommandLine"
                ).format(pid),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return result.stdout.strip() or None
        proc_cmdline = Path(f"/proc/{pid}/cmdline")
        if proc_cmdline.is_file():
            return proc_cmdline.read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _process_matches_server(state: dict[str, Any]) -> bool:
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    if not _process_exists(pid):
        return False
    command_line = _process_command_line(pid)
    if not command_line:
        return False
    normalized = command_line.lower() if os.name == "nt" else command_line
    required = [
        "nnInteractive.inference.server.main",
        str(Path(str(state.get("model_dir", ""))).resolve()),
        str(state.get("ownership_token", "")),
    ]
    if os.name == "nt":
        required = [value.lower() for value in required]
    return all(value and value in normalized for value in required)


def _server_running(server_url: str, api_key: str | None = None) -> bool:
    """Check whether the expected server answers its health endpoint."""
    import urllib.request

    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        req = urllib.request.Request(f"{server_url}/healthz", headers=headers)
        resp = urllib.request.urlopen(req, timeout=3)
        return resp.status == 200
    except Exception:
        return False


def _remove_server_state(path: Path, ownership_token: str | None = None) -> None:
    state = _load_server_state(path)
    if ownership_token and state and state.get("ownership_token") != ownership_token:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _terminate_owned_server(state: dict[str, Any]) -> bool:
    """Terminate only a process whose command line matches our ownership record."""
    if not _process_matches_server(state):
        return False
    pid = int(state["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    deadline = time.time() + 10
    while time.time() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(0.25)
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return True


def _touch_server_activity(state_path: Path, ownership_token: str) -> None:
    state = _load_server_state(state_path)
    if not state or state.get("ownership_token") != ownership_token:
        return
    state["last_activity_epoch"] = time.time()
    _write_server_state(state_path, state)


def _watchdog_main(state_path_value: str, ownership_token: str) -> int:
    state_path = Path(state_path_value)
    while True:
        state = _load_server_state(state_path)
        if not state or state.get("ownership_token") != ownership_token:
            return 0
        if not _process_matches_server(state):
            _remove_server_state(state_path, ownership_token)
            return 0
        idle_timeout = float(state.get("service_idle_timeout_seconds", SERVER_IDLE_TIMEOUT))
        last_activity = float(state.get("last_activity_epoch", time.time()))
        remaining = idle_timeout - (time.time() - last_activity)
        if remaining <= 0:
            _terminate_owned_server(state)
            _remove_server_state(state_path, ownership_token)
            return 0
        time.sleep(max(1.0, min(30.0, remaining)))


def _start_watchdog(state_path: Path, ownership_token: str) -> None:
    subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--watchdog",
            str(state_path),
            ownership_token,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def _start_server(
    model_dir: str,
    device: str,
    service_idle_timeout_seconds: float,
) -> tuple[subprocess.Popen, dict[str, Any]]:
    """Start the nnInteractive server as a background subprocess.

    Returns the Popen object. The server processes requests after the model
    is loaded (~10-30 seconds on first start).
    """
    # Use the same Python that's running this bridge (guaranteed to have the
    # nnInteractive package available, whether from venv or portable bundle).
    python_exe = sys.executable
    log_path = _server_log_path(model_dir)
    state_path = _server_state_path(model_dir)
    ownership_token = uuid.uuid4().hex

    # Build env: ensure site-packages from the portable bundle are on PYTHONPATH.
    env = os.environ.copy()
    bundle_site = os.path.join(os.path.dirname(python_exe), "..", "Lib", "site-packages")
    bundle_site = os.path.normpath(bundle_site)
    if os.path.isdir(bundle_site):
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = bundle_site + (";" + existing if existing else "")

    cmd = [
        python_exe,
        "-m", "nnInteractive.inference.server.main",
        "--model-dir", str(model_dir),
        "--fold", "all",
        "--host", SERVER_HOST,
        "--port", str(SERVER_PORT),
        "--device", device,
        "--idle-timeout-seconds", "1800",  # Reap an inactive client session after 30 min.
        "--liveness-timeout-seconds", "120",
        "--max-sessions", "1",
        "--api-key", ownership_token,
    ]

    with open(log_path, "a") as log_fh:
        log_fh.write(f"\n{'='*60}\n")
        log_fh.write(f"Starting nnInteractive server at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        logged_cmd = ["<redacted>" if value == ownership_token else value for value in cmd]
        log_fh.write(f"Command: {' '.join(logged_cmd)}\n")
        log_fh.flush()

        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,  # Detach from parent process group
        )

    state = {
        "schema_version": "nninteractive_owned_server.v1",
        "pid": proc.pid,
        "server_url": SERVER_URL,
        "model_dir": str(Path(model_dir).resolve()),
        "device": device,
        "ownership_token": ownership_token,
        "started_at_epoch": time.time(),
        "last_activity_epoch": time.time(),
        "service_idle_timeout_seconds": float(service_idle_timeout_seconds),
    }
    _write_server_state(state_path, state)
    _start_watchdog(state_path, ownership_token)
    return proc, state


def _wait_for_server(api_key: str, timeout: float = SERVER_STARTUP_TIMEOUT) -> bool:
    """Block until the server responds to healthz or timeout.

    Returns True if the server is ready.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_running(SERVER_URL, api_key):
            return True
        time.sleep(HEALTHZ_RETRY_INTERVAL)
    return False


def _ensure_server(
    model_dir: str,
    device: str,
    service_idle_timeout_seconds: float = SERVER_IDLE_TIMEOUT,
) -> tuple[bool, str, str]:
    """Ensure the nnInteractive server is running; start it if needed.

    Returns (first_call, server_url, api_key).
      - first_call=True means the server was just started (model loading).
    """
    state_path = _server_state_path(model_dir)
    state = _load_server_state(state_path)
    expected_model = str(Path(model_dir).resolve())
    if state and _process_matches_server(state):
        matches_request = (
            str(state.get("model_dir")) == expected_model
            and str(state.get("device")) == str(device)
        )
        api_key = str(state.get("ownership_token") or "")
        if matches_request and _server_running(SERVER_URL, api_key):
            _touch_server_activity(state_path, api_key)
            return False, SERVER_URL, api_key
        _terminate_owned_server(state)
    if state:
        _remove_server_state(state_path, str(state.get("ownership_token") or ""))

    legacy_pid = Path(model_dir).parent / ".nninteractive_server.pid"
    try:
        legacy_pid.unlink()
    except FileNotFoundError:
        pass

    if _server_running(SERVER_URL):
        raise RuntimeError(
            f"Port {SERVER_PORT} is already used by a server not owned by this integration. "
            "Stop it, or configure an explicit server_url with auto_start_server disabled."
        )

    proc, state = _start_server(model_dir, device, service_idle_timeout_seconds)
    api_key = str(state["ownership_token"])

    # Wait for the server to be ready.
    ready = _wait_for_server(api_key)
    if not ready:
        # Server failed to start. Clean up.
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        _remove_server_state(state_path, api_key)
        raise RuntimeError(
            "nnInteractive server failed to start within {0}s. "
            "Check log: {1}".format(SERVER_STARTUP_TIMEOUT, _server_log_path(model_dir))
        )

    return True, SERVER_URL, api_key


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

def _connect_remote(server_url: str, api_key: str | None = None) -> Any:
    """Connect to a running nnInteractive server."""
    from nnInteractive.inference.remote import nnInteractiveRemoteInferenceSession

    if api_key is None:
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


def _polyline_to_mask(shape: list[int], points: list[list[int]]) -> np.ndarray:
    """Rasterize voxel-index polyline points into a sparse 3D prompt mask."""
    result = np.zeros(tuple(shape), dtype=bool)
    if not points:
        return result
    if len(points) == 1:
        return _point_mask(shape, points[0])
    previous = np.asarray(points[0], dtype=float)
    for current_value in points[1:]:
        current = np.asarray(current_value, dtype=float)
        steps = max(int(np.max(np.abs(current - previous))), 1) + 1
        samples = np.rint(
            np.linspace(previous, current, num=steps, endpoint=True)
        ).astype(int)
        for sample in samples:
            if all(0 <= int(sample[axis]) < int(shape[axis]) for axis in range(3)):
                result[tuple(int(value) for value in sample)] = True
        previous = current
    return result


def _filled_region_boundary(mask: np.ndarray) -> np.ndarray:
    """Convert a filled Mimics Lasso region into per-slice closed contours."""
    if not np.any(mask):
        return mask.astype(bool)
    candidates: list[tuple[int, np.ndarray]] = []
    for axis in range(3):
        reduce_axes = tuple(index for index in range(3) if index != axis)
        slices = np.where(mask.any(axis=reduce_axes))[0]
        if len(slices):
            candidates.append((axis, slices))
    axis, _ = min(candidates, key=lambda item: len(item[1]))
    moved = np.moveaxis(mask.astype(bool), axis, 0)
    boundary = np.zeros_like(moved, dtype=bool)
    for index, plane in enumerate(moved):
        if not np.any(plane):
            continue
        interior = plane.copy()
        interior[0, :] = False
        interior[-1, :] = False
        interior[:, 0] = False
        interior[:, -1] = False
        interior[1:-1, 1:-1] &= (
            plane[:-2, 1:-1]
            & plane[2:, 1:-1]
            & plane[1:-1, :-2]
            & plane[1:-1, 2:]
        )
        boundary[index] = plane & ~interior
    return np.moveaxis(boundary, 0, axis)


def _point_mask(shape: list[int], point: list[int]) -> np.ndarray:
    result = np.zeros(tuple(shape), dtype=bool)
    if len(point) != 3:
        raise RuntimeError(f"Point must have three indexes: {point}")
    indexes = tuple(int(value) for value in point)
    if not all(0 <= indexes[axis] < int(shape[axis]) for axis in range(3)):
        raise RuntimeError(f"Point is outside image bounds: {point} vs {shape}")
    result[indexes] = True
    return result


def _legacy_interactions(input_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert the first prototype protocol to the ordered interaction form."""
    interaction_path = input_data.get("interaction_path")
    if not interaction_path:
        return []
    result = [
        {
            "interaction_type": input_data.get("interaction_type", "scribble"),
            "include_interaction": input_data.get("include_interaction", True),
            "mask_path": interaction_path,
            "mask_shape": input_data.get("interaction_shape"),
            "coordinates": "mimics",
        }
    ]
    if input_data.get("bg_interaction_path"):
        result.append(
            {
                "interaction_type": input_data.get("interaction_type", "scribble"),
                "include_interaction": False,
                "mask_path": input_data["bg_interaction_path"],
                "mask_shape": input_data.get("interaction_shape"),
                "coordinates": "mimics",
            }
        )
    return result


def _interaction_mask(
    interaction: dict[str, Any],
    *,
    mimics_shape: list[int],
    platform_shape: list[int],
    buffer_mapping: dict[str, Any],
) -> np.ndarray:
    coordinates = interaction.get("coordinates", "mimics")
    shape = mimics_shape if coordinates == "mimics" else platform_shape
    if interaction.get("point") is not None:
        mask = _point_mask(shape, interaction["point"])
    elif interaction.get("polyline_points") is not None:
        mask = _polyline_to_mask(shape, interaction["polyline_points"])
    elif interaction.get("bbox") is not None:
        mask = np.zeros(tuple(shape), dtype=bool)
        bbox = interaction["bbox"]
        mask[
            int(bbox[0][0]):int(bbox[0][1]),
            int(bbox[1][0]):int(bbox[1][1]),
            int(bbox[2][0]):int(bbox[2][1]),
        ] = True
    elif interaction.get("mask_path"):
        mask_shape = interaction.get("mask_shape") or shape
        loaded = load_interaction_u8(interaction["mask_path"], mask_shape)
        bbox = interaction.get("interaction_bbox")
        if bbox:
            mask = np.zeros(tuple(shape), dtype=bool)
            expected_shape = tuple(
                int(bbox[axis][1]) - int(bbox[axis][0])
                for axis in range(3)
            )
            if tuple(loaded.shape) != expected_shape:
                raise RuntimeError(
                    f"Interaction crop shape mismatch: {loaded.shape} != {expected_shape}"
                )
            mask[
                int(bbox[0][0]):int(bbox[0][1]),
                int(bbox[1][0]):int(bbox[1][1]),
                int(bbox[2][0]):int(bbox[2][1]),
            ] = loaded
        else:
            mask = loaded
    else:
        raise RuntimeError(
            f"Interaction has no point, polyline, bbox, or mask: {interaction}"
        )
    if coordinates == "mimics":
        return mimics_to_platform(mask, buffer_mapping)
    if coordinates == "platform":
        return mask
    raise RuntimeError(f"Unsupported interaction coordinates: {coordinates}")


def _apply_interaction(
    session: Any,
    interaction_mask: np.ndarray,
    interaction_type: str,
    include_interaction: bool,
) -> None:
    if interaction_type == "point":
        nonzero = np.argwhere(interaction_mask)
        if len(nonzero):
            session.add_point_interaction(
                tuple(int(value) for value in nonzero[0]),
                include_interaction=include_interaction,
            )
        return
    if interaction_type == "box":
        bbox = _nonzero_bbox(interaction_mask)
        if bbox is not None:
            session.add_bbox_interaction(bbox, include_interaction=include_interaction)
        return
    if interaction_type == "lasso":
        interaction_mask = _filled_region_boundary(interaction_mask)
        add_method = session.add_lasso_interaction
    elif interaction_type == "scribble":
        add_method = session.add_scribble_interaction
    else:
        raise RuntimeError(f"Unsupported interaction_type: {interaction_type}")
    for crop, bbox in _iter_2d_interaction_crops(interaction_mask):
        add_method(
            crop,
            include_interaction=include_interaction,
            interaction_bbox=bbox,
        )


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

    required = ["output_path", "model_dir"]
    missing = [key for key in required if key not in input_data]
    if missing:
        return {"status": "error", "error": f"Missing required keys: {missing}"}

    image_path: str | None = input_data.get("image_path")
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

        interactions = input_data.get("interactions") or _legacy_interactions(input_data)
        if not interactions:
            return {
                "status": "skipped",
                "output_path": output_path,
                "elapsed_seconds": round(time.time() - started, 2),
                "reason": "no_interactions",
            }

        platform_shape = [int(value) for value in image_np.shape[1:]]
        if input_data.get("image_buffer_shape"):
            mimics_shape = [int(value) for value in input_data["image_buffer_shape"]]
        elif input_data.get("interaction_shape"):
            mimics_shape = [int(value) for value in input_data["interaction_shape"]]
        else:
            mimics_shape = list(platform_shape)

        server_url = input_data.get("server_url") or SERVER_URL
        auto_start = bool(input_data.get("auto_start_server", True))
        server_api_key = os.environ.get("NN_INTERACTIVE_API_KEY")
        owned_state_path = None
        owned_token = None
        if auto_start and server_url == SERVER_URL:
            first_call, server_url, server_api_key = _ensure_server(
                model_dir,
                device,
                float(input_data.get("server_idle_timeout_seconds", SERVER_IDLE_TIMEOUT)),
            )
            owned_state_path = _server_state_path(model_dir)
            owned_token = server_api_key
        else:
            first_call = False

        if owned_state_path is not None and owned_token:
            _touch_server_activity(owned_state_path, owned_token)
        session = _connect_remote(server_url, server_api_key)
        mode = "remote"
        model_license = None
        try:
            session.set_image(image_np)
            target = np.zeros(image_np.shape[1:], dtype=np.uint8)
            session.set_target_buffer(target)

            initial_seg_path: str | None = input_data.get("initial_seg_path")
            if initial_seg_path:
                initial_shape = input_data.get("initial_seg_shape") or mimics_shape
                initial_mimics = load_interaction_u8(initial_seg_path, initial_shape)
                if np.any(initial_mimics):
                    initial_platform = mimics_to_platform(initial_mimics, buffer_mapping)
                    try:
                        session.add_initial_seg_interaction(
                            initial_platform.astype(np.uint8),
                            run_prediction=False,
                        )
                    except TypeError:
                        # Legacy nnInteractive API has no run_prediction kwarg and triggers
                        # inference immediately on add. The final result is still produced by
                        # the interactions below, but this extra inference is version-dependent,
                        # so surface it rather than running silently.
                        print(
                            "nninteractive_bridge: add_initial_seg_interaction has no run_prediction "
                            "kwarg; using legacy API (may trigger an extra inference pass)",
                            file=sys.stderr,
                        )
                        session.add_initial_seg_interaction(
                            initial_platform.astype(np.uint8)
                        )

            applied = 0
            for interaction in interactions:
                interaction_platform = _interaction_mask(
                    interaction,
                    mimics_shape=mimics_shape,
                    platform_shape=platform_shape,
                    buffer_mapping=buffer_mapping,
                )
                if not np.any(interaction_platform):
                    continue
                _apply_interaction(
                    session,
                    interaction_platform,
                    str(interaction.get("interaction_type", "scribble")),
                    bool(interaction.get("include_interaction", True)),
                )
                applied += 1
            if applied == 0:
                return {
                    "status": "skipped",
                    "output_path": output_path,
                    "elapsed_seconds": round(time.time() - started, 2),
                    "reason": "interactions_empty",
                }

            result_platform = np.asarray(target, dtype=np.uint8)
            if applied and not np.any(result_platform):
                # set_target_buffer is expected to fill this array in place; if it stayed
                # all-zero despite applied interactions, the nnInteractive version likely
                # wrote to a different buffer. Surface this so the failure is not silent.
                print(
                    "nninteractive_bridge: target buffer is empty after interactions; "
                    "set_target_buffer in-place fill may not be supported by this nnInteractive version",
                    file=sys.stderr,
                )
            result_mimics = platform_to_mimics(result_platform, buffer_mapping)
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "wb") as handle:
                handle.write(result_mimics.tobytes(order="C"))
            model_license = getattr(session, "license", None)
        finally:
            try:
                session.close()
            except Exception:
                pass
            if owned_state_path is not None and owned_token:
                _touch_server_activity(owned_state_path, owned_token)

        elapsed = time.time() - started
        return {
            "status": "refined",
            "output_path": output_path,
            "elapsed_seconds": round(elapsed, 2),
            "mode": mode,
            "first_call": first_call,
            "interaction_count": len(interactions),
            "model_license": model_license,
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
    if len(sys.argv) == 4 and sys.argv[1] == "--watchdog":
        return _watchdog_main(sys.argv[2], sys.argv[3])
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
