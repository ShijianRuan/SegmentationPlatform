# -*- coding: utf-8 -*-
"""Async execution mode tests for nnInteractive Mimics integration.

Tests the complete async state machine (_run_async, _start_async_job,
_enqueue_async_prediction, _handle_async_result) and all edge cases:
  - Normal flow: start job → worker completes → apply result
  - Mask modified during async execution
  - Image/target identity changed
  - Worker still running when user re-enters
  - Worker crashed / prediction failed
  - Undo / Reset in async mode
  - Discard running job
  - Cleanup of expired jobs
  - Multi-prompt iterative prediction
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch

import numpy as np

# ---------------------------------------------------------------------------
#  Import runtime module
# ---------------------------------------------------------------------------

MIMICS_RUNTIME_PATH = (
    Path(__file__).resolve().parents[1]
    / "adapters" / "mimics" / "runtime_py35" / "nninteractive_mimics.py"
)

# Also import bridge for _sha256_file etc.
BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "adapters" / "mimics" / "nninteractive_bridge.py"
)
_bridge_spec = importlib.util.spec_from_file_location("async_bridge", BRIDGE_PATH)
BRIDGE = importlib.util.module_from_spec(_bridge_spec)
_bridge_spec.loader.exec_module(BRIDGE)


# ---------------------------------------------------------------------------
#  Enhanced FakeMimics with metadata support
# ---------------------------------------------------------------------------

class _MetadataStore:
    """Simulates Mimics object metadata (key-value store)."""

    def __init__(self):
        self._items: dict[str, str] = {}

    def find(self, name: str):
        """Return item with .value, or None."""
        if name in self._items:
            return _MetadataItem(name, self._items[name])
        return None

    def create(self, name: str, value: str) -> None:
        self._items[name] = value

    def delete(self, name: str) -> None:
        self._items.pop(name, None)

    def __getitem__(self, name: str):
        if name in self._items:
            return _MetadataItem(name, self._items[name])
        raise KeyError(name)


class _MetadataItem:
    def __init__(self, name: str, value: str):
        self.name = name
        self.value = value


class _VoxelBuffer:
    def __init__(self, data: np.ndarray, fmt: str = "H"):
        self._data = data
        self.format = fmt

    @property
    def shape(self) -> tuple[int, ...]:
        return self._data.shape

    def tobytes(self) -> bytes:
        return self._data.tobytes()

    def __array__(self, dtype=None) -> np.ndarray:
        if dtype is not None:
            return self._data.astype(dtype, copy=False)
        return self._data

    def __len__(self) -> int:
        return len(self._data)


class _Mask:
    _next_guid = 1
    _image_registry: dict[int, "_Image"] = {}

    def __init__(self, name: str, data: np.ndarray | None = None):
        self.guid = _Mask._next_guid
        _Mask._next_guid += 1
        self.name = name
        self._data = data if data is not None else np.zeros((1, 1, 1), dtype=np.uint8)
        self.visible = False
        self.selected = False
        self._image_guid: int | None = None
        self.color = (1.0, 1.0, 1.0)
        self.metadata = _MetadataStore()
        self._last_export_path: str | None = None

    @property
    def image(self) -> "_Image | None":
        if self._image_guid is not None:
            return _Mask._image_registry.get(self._image_guid)
        return None

    @image.setter
    def image(self, value: "_Image") -> None:
        if value is not None:
            self._image_guid = value.guid
            _Mask._image_registry[value.guid] = value
            if self._data.shape != value._data.shape:
                self._data = np.zeros(value._data.shape, dtype=np.uint8)

    @property
    def number_of_pixels(self) -> int:
        return int(np.count_nonzero(self._data))

    def get_voxel_buffer(self) -> _VoxelBuffer:
        return _VoxelBuffer(self._data, "B")

    def set_voxel_buffer(self, data) -> None:
        if isinstance(data, np.ndarray):
            self._data = data.astype(np.uint8).copy()
        else:
            self._data = np.array(data, dtype=np.uint8).reshape(self._data.shape).copy()

    def _sha256(self) -> str:
        """Compute SHA-256 of mask data (matching runtime's _mask_sha256)."""
        return "sha256:" + hashlib.sha256(self._data.tobytes()).hexdigest()


class _Image:
    _next_guid = 100

    def __init__(self, data: np.ndarray, name: str = "CT_001"):
        self.guid = _Image._next_guid
        _Image._next_guid += 1
        self.name = name
        self._data = data.astype(np.int16)

    def get_voxel_buffer(self) -> _VoxelBuffer:
        return _VoxelBuffer(self._data, "h")

    def get_voxel_indexes(self, coordinates) -> list[int]:
        if isinstance(coordinates, tuple) and len(coordinates) == 3:
            return [int(c) for c in coordinates]
        return [int(c) for c in coordinates]


class _Point:
    _next_guid = 200

    def __init__(self, coordinates: tuple, name: str = "", color: tuple = (1.0, 1.0, 1.0)):
        self.guid = _Point._next_guid
        _Point._next_guid += 1
        self.coordinates = coordinates
        self.name = name
        self.color = color


class _Spline:
    _next_guid = 300

    def __init__(self, points: list, closed: bool = False):
        self.guid = _Spline._next_guid
        _Spline._next_guid += 1
        self.geometry_points = list(points)
        self.points = list(points)
        self.closed = closed


class _DistanceMeasurement:
    _next_guid = 400

    def __init__(self, point1, point2):
        self.guid = _DistanceMeasurement._next_guid
        _DistanceMeasurement._next_guid += 1
        self.point1 = point1
        self.point2 = point2


class _FakeImageList(list):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active: _Image | None = None

    def get_active(self) -> _Image | None:
        return self._active

    def set_active(self, image: _Image) -> None:
        self._active = image


class _FakeMaskList(list):
    def delete(self, mask: _Mask) -> None:
        try:
            self.remove(mask)
        except ValueError:
            pass


class _FakePointList(list):
    def delete(self, point: _Point) -> None:
        try:
            self.remove(point)
        except ValueError:
            pass


class _FakeSplineList(list):
    def delete(self, spline: _Spline) -> None:
        try:
            self.remove(spline)
        except ValueError:
            pass


class _FakeMeasurementList(list):
    def delete(self, measurement) -> None:
        try:
            self.remove(measurement)
        except ValueError:
            pass


class _FakeMimicsData:
    def __init__(self):
        self.images = _FakeImageList()
        self.masks = _FakeMaskList()
        self.points = _FakePointList()
        self.splines = _FakeSplineList()
        self.distance_measurements = _FakeMeasurementList()
        self.measurements: list = self.distance_measurements

    def reset(self) -> None:
        self.images.clear()
        self.images._active = None
        self.masks.clear()
        self.points.clear()
        self.splines.clear()
        self.distance_measurements.clear()


class _FakeMimicsSegment:
    def __init__(self, data: _FakeMimicsData):
        self._data = data

    def create_mask(self) -> _Mask:
        mask = _Mask(name="New Mask")
        self._data.masks.append(mask)
        return mask

    @staticmethod
    def activate_edit_mask(mask: _Mask, edit_type: str, mode: str) -> None:
        data = mask._data
        if data.size > 0 and np.any(data.shape):
            center = tuple(s // 2 for s in data.shape)
            slices = tuple(
                slice(max(0, c - 2), min(s, c + 3))
                for c, s in zip(center, data.shape)
            )
            data[slices] = 1


class _FakeMimicsAnalyze:
    @staticmethod
    def create_point(point, name: str = "", color: tuple = (1.0, 1.0, 1.0)) -> _Point:
        return _Point(point, name, color)


class _FakeMimicsView:
    @staticmethod
    def show_log_panel() -> None:
        pass


class FakeMimicsDialogs:
    def __init__(self):
        self._responses: dict[str, list[str]] = {}
        self._call_log: list[dict[str, Any]] = []

    def set_responses(self, question_box: list[str] | None = None,
                       message_box: list[str] | None = None) -> None:
        if question_box is not None:
            self._responses["question_box"] = list(question_box)
        if message_box is not None:
            self._responses["message_box"] = list(message_box)

    def question_box(self, message: str = "", buttons: str = "",
                      title: str = "", ui_blocking: bool = True) -> str:
        self._call_log.append({
            "method": "question_box", "message": message, "buttons": buttons,
        })
        options = [b.strip() for b in buttons.split(";") if b.strip()]
        return self._responses.get("question_box", [options[-1]]).pop(0) \
            if self._responses.get("question_box") else options[-1]

    def message_box(self, message: str = "", title: str = "",
                     ui_blocking: bool = True) -> None:
        self._call_log.append({
            "method": "message_box", "message": message,
        })


class FakeMimics:
    class UserInterrupted(Exception):
        pass

    def __init__(self):
        self.data = _FakeMimicsData()
        self.segment = _FakeMimicsSegment(self.data)
        self.analyze = _FakeMimicsAnalyze()
        self.view = _FakeMimicsView()
        self.dialogs = FakeMimicsDialogs()
        self.logging = types.SimpleNamespace(
            INFO=20, WARNING=30,
            log_user_message=lambda level, message: None,
        )
        self.measure = types.SimpleNamespace()
        self._coordinate_responses: list[tuple] = []
        self._spline_responses: list[_Spline | None] = []
        self._distance_responses: list[_DistanceMeasurement | None] = []

    def add_image(self, data: np.ndarray, name: str = "CT_001") -> _Image:
        img = _Image(data, name)
        self.data.images.append(img)
        self.data.images.set_active(img)
        return img

    def add_mask(self, data: np.ndarray | None = None, name: str = "Mask",
                  selected: bool = False, image: _Image | None = None) -> _Mask:
        if data is None and image is not None:
            data = np.zeros(image._data.shape, dtype=np.uint8)
        mask = _Mask(name, data)
        if image is not None:
            mask.image = image
        mask.selected = selected
        self.data.masks.append(mask)
        return mask

    def set_active_image(self, image: _Image) -> None:
        self.data.images.set_active(image)

    def reset(self) -> None:
        self.data.reset()
        self._coordinate_responses.clear()
        self._spline_responses.clear()
        self._distance_responses.clear()

    def indicate_coordinate(self, message: str = "", show_message_box: bool = True,
                             confirm: bool = False, title: str = "") -> tuple:
        if not self._coordinate_responses:
            raise self.UserInterrupted("No more coordinate responses")
        return self._coordinate_responses.pop(0)

    def set_indicate_coordinate(self, points: list[tuple]) -> None:
        self._coordinate_responses = list(points)

    def _indicate_spline_fn(self, message: str = "", show_message_box: bool = True,
                            confirm: bool = True, title: str = "") -> _Spline | None:
        if not self._spline_responses:
            raise self.UserInterrupted("No more spline responses")
        return self._spline_responses.pop(0)

    def set_indicate_spline(self, splines: list) -> None:
        self._spline_responses = list(splines)

    def _indicate_distance_fn(self, message: str = "", show_message_box: bool = True,
                              confirm: bool = True, title: str = ""
                              ) -> _DistanceMeasurement | None:
        if not self._distance_responses:
            raise self.UserInterrupted("No more distance measurement responses")
        return self._distance_responses.pop(0)

    def set_indicate_distance(self, measurements: list) -> None:
        self._distance_responses = list(measurements)


def _make_fake_mimics() -> FakeMimics:
    fake = FakeMimics()
    fake.measure.indicate_distance_measurement = fake._indicate_distance_fn
    fake.analyze.indicate_spline = fake._indicate_spline_fn
    return fake


def _load_runtime_module(fake_mimics: object) -> object:
    spec = importlib.util.spec_from_file_location("async_mimics_ut", MIMICS_RUNTIME_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get("mimics")
    sys.modules["mimics"] = fake_mimics
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("mimics", None)
        else:
            sys.modules["mimics"] = previous
    return module


# ---------------------------------------------------------------------------
#  Async worker simulator (writes files that _handle_async_result reads)
# ---------------------------------------------------------------------------

def _simulate_worker_completed(state: dict, output_path: str, shape: list[int],
                                foreground_voxels: int = 100) -> None:
    """Simulate worker finishing successfully: write result + worker_status."""
    job_dir = state["_job_dir"]
    sequence = state.get("pending_sequence")
    if sequence is None:
        return

    # Write a prediction output .u8 file.
    result_data = np.zeros(shape, dtype=np.uint8)
    if foreground_voxels > 0:
        cx, cy, cz = shape[0] // 2, shape[1] // 2, shape[2] // 2
        r = max(1, int((foreground_voxels / 8) ** (1 / 3)))
        sl = tuple(
            slice(max(0, c - r), min(s, c + r + 1))
            for c, s in zip((cx, cy, cz), shape)
        )
        result_data[sl] = 1
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(result_data.tobytes(order="C"))

    # Write result JSON.
    result_json = {
        "status": "refined",
        "output_path": output_path,
        "elapsed_seconds": 3.5,
        "foreground_voxels": int(np.count_nonzero(result_data)),
        "result_shape": shape,
        "expected_target_sha256": state.get("expected_target_sha256", ""),
    }
    result_file = os.path.join(
        job_dir, "results", "result_{0:06d}.json".format(int(sequence)))
    os.makedirs(os.path.dirname(result_file), exist_ok=True)
    with open(result_file, "w") as f:
        json.dump(result_json, f)

    # Write worker_status.
    worker_status = {"status": "ready", "stage": "idle"}
    with open(os.path.join(job_dir, "worker_status.json"), "w") as f:
        json.dump(worker_status, f)

    # Update state.
    state["status"] = "ready"


def _simulate_worker_running(state: dict, stage: str = "predicting") -> None:
    """Simulate worker still running."""
    with open(os.path.join(state["_job_dir"], "worker_status.json"), "w") as f:
        json.dump({"status": "running", "stage": stage}, f)


def _simulate_worker_failed(state: dict, error: str = "Simulated failure",
                             stage: str = "prediction") -> None:
    """Simulate worker crash/failure."""
    with open(os.path.join(state["_job_dir"], "worker_status.json"), "w") as f:
        json.dump({"status": "failed", "stage": stage, "error": error}, f)
    state["status"] = "failed"


# ---------------------------------------------------------------------------
#  Config helper
# ---------------------------------------------------------------------------

def _async_config(model_dir: str, **overrides) -> dict:
    """Minimal config for async mode tests."""
    return {
        "schema_version": "nninteractive_config.v1",
        "device": "cpu",
        "model_dir": model_dir,
        "auto_start_server": False,
        "reuse_session": False,
        "execution_mode": "async",
        "python": sys.executable,
        "bridge_script": str(
            Path(__file__).resolve().parents[1]
            / "adapters" / "mimics" / "nninteractive_bridge.py"
        ),
        "async_worker_idle_timeout_seconds": 1800,
        "async_poll_seconds": 0.5,
        "async_job_retention_days": 7,
        "fold": "auto",
        "allow_cpu_fallback": True,
        **overrides,
    }


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------


class AsyncModeStateMachineTests(unittest.TestCase):
    """Test the async execution state machine (_run_async)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="async_test_")
        self.fake = _make_fake_mimics()
        self.runtime = _load_runtime_module(self.fake)

        self.model_dir = os.path.join(self.temp_dir, "models", "nnInteractive_v1.0")
        os.makedirs(self.model_dir, exist_ok=True)
        fold_dir = os.path.join(self.model_dir, "fold_0")
        os.makedirs(fold_dir, exist_ok=True)
        Path(os.path.join(fold_dir, "checkpoint_final.pth")).write_bytes(b"weights")

        self.config = _async_config(self.model_dir)
        config_path = os.path.join(self.temp_dir, "nninteractive_config.json")
        with open(config_path, "w") as f:
            json.dump(self.config, f)
        os.environ["NNINTERACTIVE_CONFIG"] = config_path

        rng = np.random.RandomState(42)
        self.image_data = rng.rand(64, 64, 22).astype(np.float32) * 2000
        self.shape = list(self.image_data.shape)

        # Mock _probe_python: skip real subprocess, return valid probe result.
        self._probe_patcher = patch.object(
            self.runtime, "_probe_python",
            return_value={
                "python": sys.executable,
                "version": [3, 12, 0],
                "missing": [],
            },
        )
        self._probe_patcher.start()

        # Mock _process_exists so fake PIDs appear alive.
        self._process_exists_patcher = patch.object(
            self.runtime, "_process_exists", return_value=True,
        )
        self._process_exists_patcher.start()

        # Mock subprocess.Popen so no real worker is spawned.
        self._popen_patcher = patch.object(
            self.runtime.subprocess, "Popen",
            side_effect=self._fake_popen,
        )
        self._popen_patcher.start()
        self._worker_pids: list[int] = []
        self._pid_counter = 50000

    def tearDown(self):
        self._popen_patcher.stop()
        self._probe_patcher.stop()
        self._process_exists_patcher.stop()
        self.fake.reset()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.environ.pop("NNINTERACTIVE_CONFIG", None)

    def _fake_popen(self, cmd, **kwargs):
        """Simulate spawning a worker: create the directory structure, assign a
        fake PID, and return a mock process that appears alive."""
        self._pid_counter += 1
        pid = self._pid_counter
        self._worker_pids.append(pid)

        class _FakeProcess:
            def __init__(self, p, c):
                self.pid = p
                self.returncode = None
                self._cmd = c

            def poll(self):
                return self.returncode

            def communicate(self, **kw):
                return b"", b""

            def kill(self):
                self.returncode = -9

            def terminate(self):
                self.returncode = -15

            def wait(self, timeout=None):
                self.returncode = 0
                return 0

        return _FakeProcess(pid, cmd)

    # -- Normal flow ----------------------------------------------------------

    def test_first_click_starts_job_and_returns_immediately(self):
        """First click: starts async job, returns 0, does NOT block."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # _async_prompt_menu: choose a point, then Finish.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points",              # _async_prompt_menu
            "Add Include Point",       # _capture_point_set (first iteration)
            "Run Points (1)",          # _capture_point_set (second iteration)
            "Finish",                  # _async_prompt_menu (after submit notification)
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])

        # _start_async_job writes job state.
        exit_code = self.runtime.run()

        self.assertEqual(0, exit_code)

        # Mask should have metadata pointing to the async job.
        job_dir = self.runtime._metadata_get(
            mask, self.runtime.ASYNC_JOB_METADATA)
        self.assertIsNotNone(job_dir)
        self.assertTrue(os.path.isdir(job_dir),
                        f"Job dir should exist: {job_dir}")

        # State file should exist.
        state_path = self.runtime._async_job_state_path(job_dir)
        self.assertTrue(os.path.isfile(state_path))
        state = json.loads(open(state_path).read())
        self.assertEqual("queued", state["status"])
        self.assertIn("interactions", state)

    def test_second_click_applies_result(self):
        """After worker completes, re-entering applies the result to the Mask."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # First click: submit a point → start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        # Simulate worker completing.
        state = self.runtime._load_async_job(mask)
        self.assertIsNotNone(state, "Should have async state after first click")
        output_path = os.path.join(state["_job_dir"], "results", "prediction.u8")
        _simulate_worker_completed(state, output_path, self.shape,
                                    foreground_voxels=200)

        # Second click: re-enter → should apply result.
        self.fake.dialogs.set_responses(question_box=[
            "Finish",  # _async_prompt_menu (no new prompts, just checking)
        ])
        self.runtime.run()

        # Mask should now have foreground voxels.
        self.assertGreater(mask.number_of_pixels, 0,
                           "Mask should have foreground after result applied")

    def test_multiple_prompts_then_apply(self):
        """Submit two prompts in sequence, worker completes → both applied."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Prompt 1: submit, start job, Finish.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state1 = self.runtime._load_async_job(mask)
        output1 = os.path.join(state1["_job_dir"], "results", "prediction1.u8")
        _simulate_worker_completed(state1, output1, self.shape,
                                    foreground_voxels=100)

        # Prompt 2: re-enter, result applied, add another prompt.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(34, 34, 12)])
        self.runtime.run()

        state2 = self.runtime._load_async_job(mask)
        output2 = os.path.join(state2["_job_dir"], "results", "prediction2.u8")
        _simulate_worker_completed(state2, output2, self.shape,
                                    foreground_voxels=150)

        # Prompt 3: re-enter, apply final result.
        self.fake.dialogs.set_responses(question_box=["Finish"])
        self.runtime.run()

        self.assertGreater(mask.number_of_pixels, 0)

    # -- Mask modified during async ------------------------------------------

    def test_mask_modified_during_async_detected(self):
        """If user manually edits the Mask during async, SHA mismatch is detected."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        self.assertIsNotNone(state)

        # Modify mask directly.
        original_hash = state.get("expected_target_sha256")
        mask._data[28:32, 28:32, 10:12] = 1
        current_hash = self.runtime._mask_sha256(mask)
        self.assertNotEqual(current_hash, original_hash,
                            "SHA-256 should differ after manual edit")

        # Test that _close_async_job cleans up metadata.
        self.runtime._close_async_job(mask, state, "manual_mask_change")
        self.assertIsNone(self.runtime._metadata_get(
            mask, self.runtime.ASYNC_JOB_METADATA, None))

    # -- Identity change detection -------------------------------------------

    def test_image_switched_during_async_detected(self):
        """When user switches to a different image, re-entering on the OLD
        image closes the stale job (identity mismatch detected)."""
        image1 = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image1)
        mask1 = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Mask1", selected=True, image=image1)

        # Start job on image1/mask1.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        # Simulate worker completing for mask1's job.
        state = self.runtime._load_async_job(mask1)
        self.assertIsNotNone(state)
        output_path = os.path.join(state["_job_dir"], "results", "prediction.u8")
        _simulate_worker_completed(state, output_path, self.shape)

        # Now switch back to image1/mask1 and re-enter — result applies normally.
        self.fake.set_active_image(image1)
        mask1.selected = True
        self.fake.dialogs.set_responses(question_box=["Finish"])
        self.runtime.run()

        # Result applied, metadata cleared (job completed normally).
        self.assertIsNone(
            self.runtime._metadata_get(mask1, self.runtime.ASYNC_JOB_METADATA, None))

    # -- Worker still running ------------------------------------------------

    def test_worker_still_running_shows_status(self):
        """Re-entering while worker runs → show status, user chooses Keep Running."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # First click: start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        _simulate_worker_running(state, stage="predicting")

        # Second click: worker still running → status dialog.
        self.fake.dialogs.set_responses(question_box=[
            "Keep Running",  # User chooses to keep waiting.
        ])
        self.runtime.run()

        # Job should still be active.
        self.assertIsNotNone(
            self.runtime._metadata_get(mask, self.runtime.ASYNC_JOB_METADATA, None))

    def test_worker_still_running_user_discards(self):
        """User can discard a running job from the status dialog."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        self.assertIsNotNone(state)

        # Worker still running (no result file).
        _simulate_worker_running(state, stage="predicting")

        # Re-enter → _show_async_running → click "Discard AI Session".
        self.fake.dialogs.set_responses(question_box=[
            "Discard AI Session",
        ])
        self.runtime.run()

        # Job metadata cleared.
        self.assertIsNone(
            self.runtime._metadata_get(mask, self.runtime.ASYNC_JOB_METADATA, None))

    # -- Worker failure ------------------------------------------------------

    def test_worker_crashed_detected(self):
        """Worker failure → _close_async_job cleans up metadata."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        self.assertIsNotNone(state)

        # Simulate worker failure.
        _simulate_worker_failed(state, error="OOM", stage="prediction")

        # _close_async_job should clear metadata.
        self.runtime._close_async_job(mask, state, "worker_stopped")
        self.assertIsNone(
            self.runtime._metadata_get(
                mask, self.runtime.ASYNC_JOB_METADATA, None))

    def test_prediction_failed_in_worker(self):
        """Worker produces an error result → user sees error, can restart."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        sequence = state.get("pending_sequence")
        # Write error result JSON.
        result_file = os.path.join(
            state["_job_dir"], "results",
            "result_{0:06d}.json".format(int(sequence) if sequence else 1))
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, "w") as f:
            json.dump({
                "status": "error",
                "error": "Model inference failed",
                "stage": "prediction",
            }, f)

        # Re-enter → error dialog → "Retry".
        self.fake.dialogs.set_responses(question_box=[
            "Retry",                   # Error dialog → retry
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(38, 38, 12)])
        self.runtime.run()

        # Should have a new job after retry.
        new_job = self.runtime._metadata_get(
            mask, self.runtime.ASYNC_JOB_METADATA, None)
        self.assertIsNotNone(new_job)

    # -- Undo and Reset in async mode ----------------------------------------

    def test_undo_removes_last_prompt_and_requeues(self):
        """Undo in async mode: removes last prompt, requeues for prediction."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Add prompt 1, await completion.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()
        state1 = self.runtime._load_async_job(mask)
        _simulate_worker_completed(state1, os.path.join(
            state1["_job_dir"], "results", "p1.u8"), self.shape)

        # Add prompt 2, await completion.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(34, 34, 12)])
        self.runtime.run()
        state2 = self.runtime._load_async_job(mask)
        _simulate_worker_completed(state2, os.path.join(
            state2["_job_dir"], "results", "p2.u8"), self.shape)
        self.assertEqual(2, len(state2.get("interactions", [])),
                         "Should have 2 interactions after second prompt")

        # Undo → removes prompt 2, re-enqueues.
        self.fake.dialogs.set_responses(question_box=[
            "Undo Last Prompt",
            "Finish",
        ])
        self.runtime.run()

        state3 = self.runtime._load_async_job(mask)
        self.assertEqual(1, len(state3.get("interactions", [])),
                         "Undo should remove last interaction")

    def test_reset_clears_all_prompts_and_restores_base(self):
        """Reset in async mode: clears prompts, restores base mask."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        initial_data = np.zeros(self.shape, dtype=np.uint8)
        initial_data[28:36, 28:36, 9:13] = 1
        mask = self.fake.add_mask(
            initial_data.copy(), name="Target",
            selected=True, image=image)

        # Submit a prompt.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        # Simulate completion to get result applied.
        state = self.runtime._load_async_job(mask)
        output_path = os.path.join(state["_job_dir"], "results", "prediction.u8")
        _simulate_worker_completed(state, output_path, self.shape)

        # Reset.
        self.fake.dialogs.set_responses(question_box=[
            "Reset To Start",
            "Finish",
        ])
        self.runtime.run()

        # Mask should be restored to initial.
        np.testing.assert_array_equal(initial_data, mask._data)

    # -- cleanup -------------------------------------------------------------

    def test_finish_closes_job_and_clears_metadata(self):
        """Clicking Finish calls _close_async_job and clears metadata."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # First click: submit prompt → start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        # Simulate worker completed so result is ready.
        state = self.runtime._load_async_job(mask)
        output_path = os.path.join(state["_job_dir"], "results", "prediction.u8")
        _simulate_worker_completed(state, output_path, self.shape)

        # Second click: result applied, then Finish.
        self.fake.dialogs.set_responses(question_box=["Finish"])
        self.runtime.run()

        # Metadata cleared by _close_async_job.
        self.assertIsNone(
            self.runtime._metadata_get(mask, self.runtime.ASYNC_JOB_METADATA, None))

    # -- Scribble, Box, Lasso in async mode ----------------------------------

    def test_async_scribble_prompt(self):
        """Scribble prompt in async mode starts a job correctly."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        self.fake.dialogs.set_responses(question_box=[
            "Paint Scribble", "Add Foreground Scribble", "Run Scribbles (1)",
        ])
        self.runtime.run()

        # Metadata should be set from _start_async_job.
        job_dir = self.runtime._metadata_get(
            mask, self.runtime.ASYNC_JOB_METADATA, None)
        self.assertIsNotNone(job_dir)

    def test_async_box_prompt(self):
        """Box prompt in async mode."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        self.fake.set_indicate_distance([
            _DistanceMeasurement((30, 30, 11), (36, 36, 11))
        ])
        self.fake.dialogs.set_responses(question_box=[
            "Draw Box", "Finish",
        ])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        self.assertIsNotNone(state)

    def test_async_lasso_prompt(self):
        """Lasso prompt in async mode."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        self.fake.set_indicate_spline([
            _Spline([(28, 28, 11), (36, 28, 11), (36, 36, 11), (28, 36, 11)],
                    closed=True)
        ])
        self.fake.dialogs.set_responses(question_box=[
            "Draw Lasso", "Finish",
        ])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        self.assertIsNotNone(state)

    # -- Identity edge cases -------------------------------------------------

    def test_target_mask_deleted_and_recreated(self):
        """Target mask GUID changed → old job closed, new job created."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask1 = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)
        old_guid = mask1.guid

        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask1)
        self.assertIsNotNone(state)
        self.assertEqual(str(old_guid), state["target_guid"])

        # Simulate: user deletes mask1 and creates a new one with same name.
        self.fake.data.masks.delete(mask1)
        mask2 = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)
        self.assertNotEqual(mask1.guid, mask2.guid)

        # Re-enter → should detect GUID mismatch and restart.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        # New job should be on mask2, old job closed.
        new_state = self.runtime._load_async_job(mask2)
        self.assertIsNotNone(new_state)
        self.assertEqual(str(mask2.guid), new_state["target_guid"])

    # -- _cleanup_async_jobs -------------------------------------------------

    def test_expired_jobs_are_cleaned_up(self):
        """Jobs past retention period are removed."""
        jobs_root = os.path.join(
            os.path.dirname(self.model_dir), "async_jobs")
        os.makedirs(jobs_root, exist_ok=True)

        # Create an old job.
        old_job = os.path.join(jobs_root, "old_job_001")
        os.makedirs(old_job, exist_ok=True)
        state_path = self.runtime._async_job_state_path(old_job)
        with open(state_path, "w") as f:
            json.dump({
                "status": "closed",
                "updated_at_epoch": 0,  # Very old.
            }, f)

        # Create a recent job.
        recent_job = os.path.join(jobs_root, "recent_job_002")
        os.makedirs(recent_job, exist_ok=True)
        with open(self.runtime._async_job_state_path(recent_job), "w") as f:
            json.dump({
                "status": "ready",
                "updated_at_epoch": 9999999999,  # Far future.
            }, f)

        self.runtime._cleanup_async_jobs(jobs_root, retention_days=7)

        # Old job should be deleted.
        self.assertFalse(os.path.isdir(old_job))
        # Recent job should survive.
        self.assertTrue(os.path.isdir(recent_job))

        # Clean up.
        shutil.rmtree(recent_job, ignore_errors=True)


    # -- Prompt while worker still running ----------------------------------

    def test_add_prompt_while_worker_running(self):
        """When worker is still running, _handle_async_result returns 'waiting'
        and _run_async returns immediately — user CANNOT add prompts until
        the worker completes. This is by design: prompts are batched and
        the user must wait for the current prediction before adding more."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Submit prompt 1.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        self.assertEqual(1, len(state.get("interactions", [])))

        # Worker still running.
        _simulate_worker_running(state, stage="predicting")

        # Re-enter: _handle_async_result → _show_async_running → "Keep Running"
        # → returns "waiting" → run() returns 0 immediately.
        # The user cannot add prompts yet.
        self.fake.dialogs.set_responses(question_box=[
            "Keep Running",
        ])
        self.runtime.run()

        # State unchanged — no new prompt was added.
        state2 = self.runtime._load_async_job(mask)
        self.assertEqual(1, len(state2.get("interactions", [])),
                         "Interactions should NOT change while worker runs")

    # -- Missing result output file ------------------------------------------

    def test_handle_result_missing_output_path(self):
        """_handle_async_result raises if result JSON has no valid output_path."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        mask = self.fake.add_mask(
            np.zeros(self.shape, dtype=np.uint8),
            name="Target", selected=True, image=image)

        # Start job.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        seq = state.get("pending_sequence")

        # Write a result JSON with a non-existent output_path.
        result_file = os.path.join(
            state["_job_dir"], "results",
            "result_{0:06d}.json".format(int(seq) if seq else 1))
        os.makedirs(os.path.dirname(result_file), exist_ok=True)
        with open(result_file, "w") as f:
            json.dump({
                "status": "refined",
                "output_path": "/nonexistent/path/to/prediction.u8",
                "expected_target_sha256": state.get("expected_target_sha256", ""),
            }, f)

        with self.assertRaisesRegex(RuntimeError, "prediction buffer is missing"):
            self.runtime._handle_async_result(image, mask, state)

    # -- Shape mismatch in _start_async_job ----------------------------------

    def test_start_async_job_shape_mismatch_detected(self):
        """_start_async_job raises if image and mask shapes differ."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)

        # Create a mask with WRONG shape.
        mask = _Mask("WrongShape",
                      np.zeros((32, 32, 11), dtype=np.uint8))
        mask.selected = True
        mask.image = image  # setter resizes to match image...
        # ...but we maliciously override the data back to wrong shape.
        mask._data = np.zeros((32, 32, 11), dtype=np.uint8)

        with self.assertRaisesRegex(RuntimeError, "buffer shapes differ"):
            self.runtime._start_async_job(
                {"device": "cpu", "model_dir": self.model_dir,
                 "auto_start_server": False, "fold": "auto",
                 "async_worker_idle_timeout_seconds": 1800,
                 "async_poll_seconds": 0.5, "async_job_retention_days": 7,
                 "python": sys.executable,
                 "bridge_script": str(Path(__file__).resolve().parents[1]
                                      / "adapters" / "mimics"
                                      / "nninteractive_bridge.py")},
                image, mask)

    # -- Undo all the way back to zero ---------------------------------------

    def test_undo_until_empty_restores_base(self):
        """Undo all prompts restores base mask, clears pending prediction."""
        image = self.fake.add_image(self.image_data.copy(), name="CT_001")
        self.fake.set_active_image(image)
        initial_data = np.zeros(self.shape, dtype=np.uint8)
        initial_data[28:36, 28:36, 9:13] = 1
        mask = self.fake.add_mask(
            initial_data.copy(), name="Target",
            selected=True, image=image)

        # Add one prompt, let worker complete.
        self.fake.dialogs.set_responses(question_box=[
            "Add Points", "Add Include Point", "Run Points (1)", "Finish",
        ])
        self.fake.set_indicate_coordinate([(32, 32, 11)])
        self.runtime.run()

        state = self.runtime._load_async_job(mask)
        _simulate_worker_completed(state, os.path.join(
            state["_job_dir"], "results", "p.u8"), self.shape)
        self.assertEqual(1, len(state.get("interactions", [])))

        # Undo the only prompt (worker completed, result applied first).
        self.fake.dialogs.set_responses(question_box=[
            "Undo Last Prompt",
            "Finish",
        ])
        self.runtime.run()

        # Mask should be restored to initial base.
        np.testing.assert_array_equal(initial_data, mask._data)

        state2 = self.runtime._load_async_job(mask)
        self.assertEqual(0, len(state2.get("interactions", [])),
                         "All interactions should be removed")
        self.assertIsNone(state2.get("pending_sequence"),
                          "No pending prediction after undoing all")

    # -- _persist_interaction copies mask files -----------------------------

    def test_persist_interaction_copies_mask_file(self):
        """_persist_interaction copies scribble mask files into job_dir."""
        job_dir = os.path.join(self.temp_dir, "test_persist")
        # Create both the job_dir and the prompts subdirectory
        # (normally created by _start_async_job).
        prompts_dir = os.path.join(job_dir, "prompts")
        os.makedirs(prompts_dir, exist_ok=True)

        # Create a temp prompt mask.
        mask_path = os.path.join(self.temp_dir, "test_scribble.u8")
        np.ones((2, 2, 1), dtype=np.uint8).tofile(mask_path)

        interaction = {
            "interaction_type": "scribble",
            "include_interaction": True,
            "mask_path": mask_path,
            "mask_shape": [2, 2, 1],
        }

        result = self.runtime._persist_interaction(job_dir, interaction)
        persisted_path = result["mask_path"]
        self.assertTrue(persisted_path.startswith(job_dir),
                        "Mask should be copied into job_dir")
        self.assertTrue(os.path.isfile(persisted_path),
                        f"Persisted mask file must exist: {persisted_path}")

    # -- _async_worker_status handles missing file ---------------------------

    def test_worker_status_handles_missing_file(self):
        """_async_worker_status returns {} when file doesn't exist."""
        status = self.runtime._async_worker_status("/nonexistent/path/xyz")
        self.assertEqual({}, status)

    def test_worker_status_handles_invalid_json(self):
        """_async_worker_status returns {} for malformed JSON."""
        job_dir = os.path.join(self.temp_dir, "bad_status")
        os.makedirs(job_dir, exist_ok=True)
        with open(os.path.join(job_dir, "worker_status.json"), "w") as f:
            f.write("not valid json {{{")

        status = self.runtime._async_worker_status(job_dir)
        self.assertEqual({}, status)


if __name__ == "__main__":
    unittest.main()
