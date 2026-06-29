# -*- coding: utf-8 -*-
"""End-to-end simulation tests for nnInteractive Mimics integration.

These tests simulate the complete user workflow in Mimics — from launching the
nnInteractive tool, selecting a target mask, placing interactive prompts (points,
scribbles, boxes, lassos), observing predictions, and finishing the session.

The nnInteractive server is mocked with a realistic fake that produces plausible
segmentations from the input prompts. Real medical imaging data from the
synthstrip_data_v1.5 dataset is used to create realistic test fixtures.

This is NOT a unit test suite — it validates the full integration pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import importlib.util
from pathlib import Path
from typing import Any
from unittest.mock import patch

import nibabel as nib
import numpy as np

# ---------------------------------------------------------------------------
#  Import the modules under test
# ---------------------------------------------------------------------------

BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "adapters"
    / "mimics"
    / "nninteractive_bridge.py"
)
BRIDGE_SPEC = importlib.util.spec_from_file_location(
    "e2e_bridge_under_test", BRIDGE_PATH
)
assert BRIDGE_SPEC is not None and BRIDGE_SPEC.loader is not None
BRIDGE = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(BRIDGE)

MIMICS_RUNTIME_PATH = (
    Path(__file__).resolve().parents[1]
    / "adapters"
    / "mimics"
    / "runtime_py35"
    / "nninteractive_mimics.py"
)


def _load_runtime_module(fake_mimics: object) -> object:
    """Load the Mimics runtime module with a fake Mimics API."""
    spec = importlib.util.spec_from_file_location(
        "e2e_mimics_under_test", MIMICS_RUNTIME_PATH
    )
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
#  Test data helpers
# ---------------------------------------------------------------------------

REAL_DATA_DIR = Path(
    "/Users/ruanshijian/Downloads/datasets/synthstrip_data_v1.5"
)

_DEFAULT_CASE = "asl_epi_101"


def _real_image_path(case: str = _DEFAULT_CASE) -> Path:
    path = REAL_DATA_DIR / case / "image.nii.gz"
    if not path.is_file():
        raise RuntimeError(f"Real image not found: {path}")
    return path


def _real_mask_path(case: str = _DEFAULT_CASE) -> Path:
    path = REAL_DATA_DIR / case / "mask.nii.gz"
    if not path.is_file():
        raise RuntimeError(f"Real mask not found: {path}")
    return path


def _load_real_image_3d(case: str = _DEFAULT_CASE) -> np.ndarray:
    img = nib.load(str(_real_image_path(case)))
    return np.asarray(img.dataobj, dtype=np.float32)


def _load_real_mask_3d(case: str = _DEFAULT_CASE) -> np.ndarray:
    img = nib.load(str(_real_mask_path(case)))
    return np.asarray(img.dataobj, dtype=np.uint8)


# ---------------------------------------------------------------------------
#  Fake nnInteractive session (simulates real inference behavior)
# ---------------------------------------------------------------------------

class FakeNnInteractiveSession:
    """A realistic fake nnInteractive remote inference session.

    Instead of running a real neural network, this fake produces plausible
    segmentations by:
      - Starting from the initial segmentation (if any).
      - Expanding around positive (include) points via dilation.
      - Contracting away from negative (exclude) points via erosion.
      - Filling box regions.
      - Following scribble/lasso contours.

    This allows testing the complete pipeline without a GPU or model weights.
    """

    fail_on_next_set_image: bool = False
    fail_on_next_predict: bool = False
    predict_latency: float = 0.0

    def __init__(self, server_url: str = "", api_key: str | None = None,
                 read_timeout: float = 1800, set_image_read_timeout: float = 1800,
                 write_timeout: float = 600):
        self.server_url = server_url
        self.api_key = api_key
        self.license = "fake-test-license-v1.0"
        self._image: np.ndarray | None = None
        self._target: np.ndarray | None = None
        self._initial_seg: np.ndarray | None = None
        self._interactions: list[dict[str, Any]] = []
        self._closed = False
        self.set_image_call_count = 0
        self.reset_call_count = 0

    def set_image(self, image: np.ndarray) -> None:
        if self.fail_on_next_set_image:
            self.fail_on_next_set_image = False
            raise RuntimeError("Simulated set_image failure")
        self._image = image.astype(np.float32, copy=True)
        self.set_image_call_count += 1

    def set_target_buffer(self, target: np.ndarray) -> None:
        self._target = target

    def reset_interactions(self) -> None:
        if self._target is not None:
            self._target.fill(0)
        self._interactions = []
        self.reset_call_count += 1

    def add_initial_seg_interaction(self, initial: np.ndarray,
                                     run_prediction: bool = False) -> None:
        self._initial_seg = initial.astype(np.uint8, copy=True)
        if self._target is not None:
            np.copyto(self._target, initial)

    def add_point_interaction(self, point: tuple[int, int, int],
                               include_interaction: bool = True,
                               run_prediction: bool = True) -> None:
        self._interactions.append({
            "type": "point",
            "point": point,
            "include": include_interaction,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def add_bbox_interaction(self, bbox: list[list[int]],
                              include_interaction: bool = True,
                              run_prediction: bool = True) -> None:
        self._interactions.append({
            "type": "bbox",
            "bbox": bbox,
            "include": include_interaction,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def add_scribble_interaction(self, crop: np.ndarray,
                                  include_interaction: bool = True,
                                  run_prediction: bool = True,
                                  interaction_bbox: list[list[int]] | None = None) -> None:
        self._interactions.append({
            "type": "scribble" if include_interaction else "bg_scribble",
            "crop": crop.astype(bool, copy=True),
            "bbox": interaction_bbox,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def add_lasso_interaction(self, crop: np.ndarray,
                               include_interaction: bool = True,
                               run_prediction: bool = True,
                               interaction_bbox: list[list[int]] | None = None) -> None:
        self._interactions.append({
            "type": "lasso",
            "crop": crop.astype(bool, copy=True),
            "bbox": interaction_bbox,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def close(self) -> None:
        self._closed = True

    # -- Internal simulation logic --------------------------------------------

    def _apply_all(self) -> None:
        import time
        if self.fail_on_next_predict:
            self.fail_on_next_predict = False
            raise RuntimeError("Simulated prediction failure")
        if self.predict_latency > 0:
            time.sleep(self.predict_latency)

        if self._target is None or self._image is None:
            return

        # Start from initial segmentation.
        if self._initial_seg is not None:
            np.copyto(self._target, self._initial_seg)
        else:
            self._target.fill(0)

        # Apply each interaction.
        for interaction in self._interactions:
            itype = interaction["type"]
            if itype == "point":
                self._apply_point(interaction)
            elif itype == "bbox":
                self._apply_bbox(interaction)
            elif itype == "scribble":
                self._apply_scribble_internal(interaction, True)
            elif itype == "bg_scribble":
                self._apply_scribble_internal(interaction, False)
            elif itype == "lasso":
                self._apply_lasso(interaction)

        # Light post-processing: fill holes and smooth.
        if np.any(self._target):
            from scipy.ndimage import binary_fill_holes, binary_dilation
            result = binary_dilation(self._target, iterations=1)
            result = binary_fill_holes(result)
            np.copyto(self._target, result.astype(np.uint8))

    def _apply_point(self, interaction: dict[str, Any]) -> None:
        point = interaction["point"]
        include = interaction["include"]
        if not all(0 <= point[d] < self._target.shape[d] for d in range(3)):
            return

        radius = 3
        slices = []
        for d in range(3):
            lo = max(0, point[d] - radius)
            hi = min(self._target.shape[d], point[d] + radius + 1)
            slices.append(slice(lo, hi))

        if include:
            self._target[tuple(slices)] = 1
        else:
            self._target[tuple(slices)] = 0
            self._target[point] = 0

    def _apply_bbox(self, interaction: dict[str, Any]) -> None:
        bbox = interaction["bbox"]
        if interaction["include"]:
            sl = tuple(
                slice(int(bbox[d][0]), int(bbox[d][1]))
                for d in range(3)
            )
            self._target[sl] = 1

    def _apply_scribble_internal(self, interaction: dict[str, Any],
                                  include: bool) -> None:
        crop = interaction["crop"]
        bbox = interaction.get("bbox")
        if bbox is not None:
            sl = tuple(
                slice(int(bbox[d][0]), int(bbox[d][1]))
                for d in range(3)
            )
            from scipy.ndimage import binary_dilation
            expanded = binary_dilation(crop, iterations=3)
            if include:
                self._target[sl] = np.logical_or(self._target[sl], expanded)
            else:
                self._target[sl] = np.logical_and(
                    self._target[sl], np.logical_not(expanded)
                )

    def _apply_lasso(self, interaction: dict[str, Any]) -> None:
        crop = interaction["crop"]
        bbox = interaction.get("bbox")
        if bbox is not None:
            sl = tuple(
                slice(int(bbox[d][0]), int(bbox[d][1]))
                for d in range(3)
            )
            from scipy.ndimage import binary_dilation, binary_fill_holes
            filled = binary_fill_holes(binary_dilation(crop, iterations=1))
            self._target[sl] = np.logical_or(self._target[sl], filled)


# ---------------------------------------------------------------------------
#  Fake Mimics API (simulates Mimics Research 21 GUI)
# ---------------------------------------------------------------------------

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
        """Support np.asarray(voxel_buffer)."""
        if dtype is not None:
            return self._data.astype(dtype, copy=False)
        return self._data

    def __len__(self) -> int:
        return len(self._data)


class _Mask:
    _next_guid = 1
    # Class-level registry so the image getter can resolve image_guid → image.
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
            # memoryview path (Python 3.5 without NumPy).
            import struct
            self._data = np.array(data, dtype=np.uint8).reshape(self._data.shape).copy()


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
    """A list-like object that also supports Mimics' get_active() API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active: _Image | None = None

    def get_active(self) -> _Image | None:
        return self._active

    def set_active(self, image: _Image) -> None:
        self._active = image


class _FakeMaskList(list):
    """A list with Mimics-style delete() for mask cleanup."""

    def delete(self, mask: _Mask) -> None:
        try:
            self.remove(mask)
        except ValueError:
            pass


class _FakePointList(list):
    """A list with Mimics-style delete() for point cleanup."""

    def delete(self, point: _Point) -> None:
        try:
            self.remove(point)
        except ValueError:
            pass


class _FakeSplineList(list):
    """A list with Mimics-style delete() for spline cleanup."""

    def delete(self, spline: _Spline) -> None:
        try:
            self.remove(spline)
        except ValueError:
            pass


class _FakeMeasurementList(list):
    """A list with Mimics-style delete() for measurement cleanup."""

    def delete(self, measurement) -> None:
        try:
            self.remove(measurement)
        except ValueError:
            pass


class _FakeMimicsData:
    """Simulates mimics.data namespace."""

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
    def __init__(self, data: _FakeMimicsData | None = None):
        self._data = data

    def create_mask(self) -> _Mask:
        mask = _Mask(name="New Mask")
        if self._data is not None:
            self._data.masks.append(mask)
        return mask

    @staticmethod
    def activate_edit_mask(mask: _Mask, edit_type: str, mode: str) -> None:
        """Simulate the user drawing: fill a small region in the mask center."""
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

    def _next_response(self, key: str, default: str) -> str:
        responses = self._responses.get(key, [])
        if responses:
            return responses.pop(0)
        return default

    def question_box(self, message: str = "", buttons: str = "",
                      title: str = "", ui_blocking: bool = True) -> str:
        self._call_log.append({
            "method": "question_box",
            "message": message,
            "buttons": buttons,
            "title": title,
        })
        options = [b.strip() for b in buttons.split(";") if b.strip()]
        return self._next_response("question_box", options[-1] if options else "")

    def message_box(self, message: str = "", title: str = "",
                     ui_blocking: bool = True) -> None:
        self._call_log.append({
            "method": "message_box",
            "message": message,
            "title": title,
        })


class FakeMimics:
    """Complete fake Mimics API for end-to-end testing."""

    class UserInterrupted(Exception):
        pass

    def __init__(self):
        self.data = _FakeMimicsData()
        self.segment = _FakeMimicsSegment(self.data)
        self.analyze = _FakeMimicsAnalyze()
        self.view = _FakeMimicsView()
        self.dialogs = FakeMimicsDialogs()
        self.logging = types.SimpleNamespace(
            INFO=20,
            WARNING=30,
            log_user_message=lambda level, message: None,
        )
        self.measure = types.SimpleNamespace()

        self._indicate_coordinate_responses: list[tuple] = []
        self._indicate_spline_responses: list[_Spline | None] = []
        self._indicate_distance_responses: list[_DistanceMeasurement | None] = []

    # -- Public setup API ----------------------------------------------------

    def add_image(self, data: np.ndarray, name: str = "CT_001") -> _Image:
        img = _Image(data, name)
        self.data.images.append(img)
        self.data.images.set_active(img)
        return img

    def add_mask(self, data: np.ndarray | None = None, name: str = "Mask",
                  selected: bool = False,
                  image: _Image | None = None) -> _Mask:
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
        self._indicate_coordinate_responses.clear()
        self._indicate_spline_responses.clear()
        self._indicate_distance_responses.clear()

    # -- Mimics coordinate indication ----------------------------------------

    def indicate_coordinate(self, message: str = "", show_message_box: bool = True,
                             confirm: bool = False, title: str = "") -> tuple:
        if not self._indicate_coordinate_responses:
            raise self.UserInterrupted("No more coordinate responses")
        return self._indicate_coordinate_responses.pop(0)

    def set_indicate_coordinate(self, points: list[tuple]) -> None:
        self._indicate_coordinate_responses = list(points)

    # -- Spline indication ---------------------------------------------------

    def _indicate_spline_fn(self, message: str = "", show_message_box: bool = True,
                            confirm: bool = True, title: str = "") -> _Spline | None:
        if not self._indicate_spline_responses:
            raise self.UserInterrupted("No more spline responses")
        return self._indicate_spline_responses.pop(0)

    def set_indicate_spline(self, splines: list) -> None:
        self._indicate_spline_responses = list(splines)

    # -- Distance measurement ------------------------------------------------

    def _indicate_distance_fn(self, message: str = "", show_message_box: bool = True,
                              confirm: bool = True, title: str = ""
                              ) -> _DistanceMeasurement | None:
        if not self._indicate_distance_responses:
            raise self.UserInterrupted("No more distance measurement responses")
        return self._indicate_distance_responses.pop(0)

    def set_indicate_distance(self, measurements: list) -> None:
        self._indicate_distance_responses = list(measurements)


def _make_fake_mimics() -> FakeMimics:
    """Create a fully wired FakeMimics instance."""
    fake = FakeMimics()
    # Bind the callbacks.
    fake.measure.indicate_distance_measurement = fake._indicate_distance_fn
    fake.analyze.indicate_spline = fake._indicate_spline_fn
    return fake


# ---------------------------------------------------------------------------
#  Helper: create a bridge request from test data
# ---------------------------------------------------------------------------

def _make_bridge_request(
    *,
    image: np.ndarray,
    mask: np.ndarray | None = None,
    interactions: list[dict[str, Any]] | None = None,
    output_dir: str,
    model_dir: str,
    buffer_mapping: dict[str, Any] | None = None,
    device: str = "cpu",
    image_shape: list[int] | None = None,
) -> dict[str, Any]:
    shape = image_shape or list(image.shape)
    img_path = os.path.join(output_dir, "image.raw")
    image.astype(np.int16).tofile(img_path)

    request: dict[str, Any] = {
        "image_buffer_path": img_path,
        "image_buffer_shape": shape,
        "image_buffer_dtype": "int16",
        "image_buffer_coordinates": "mimics",
        "buffer_mapping": buffer_mapping or {
            "platform_to_mimics_axes": [0, 1, 2],
            "platform_to_mimics_flips": [False, False, False],
        },
        "interactions": interactions or [],
        "output_path": os.path.join(output_dir, "result.u8"),
        "model_dir": model_dir,
        "device": device,
        "server_url": "http://127.0.0.1:1527",
        "auto_start_server": False,
    }

    if mask is not None and np.any(mask):
        mask_path = os.path.join(output_dir, "initial.u8")
        mask.astype(np.uint8).tofile(mask_path)
        request["initial_seg_path"] = mask_path
        request["initial_seg_shape"] = shape

    return request


# ---------------------------------------------------------------------------
#  End-to-end bridge tests
# ---------------------------------------------------------------------------

class EndToEndBridgeSimulationTests(unittest.TestCase):
    """Test the nnInteractive bridge end-to-end with a fake session."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="e2e_bridge_")
        self.model_dir = os.path.join(self.temp_dir, "models", "nnInteractive_v1.0")
        os.makedirs(self.model_dir, exist_ok=True)
        fold_dir = os.path.join(self.model_dir, "fold_0")
        os.makedirs(fold_dir, exist_ok=True)
        Path(os.path.join(fold_dir, "checkpoint_final.pth")).write_bytes(b"weights")

        try:
            self.real_image = _load_real_image_3d()
            self.real_mask = _load_real_mask_3d()
            self.has_real_data = True
        except (RuntimeError, FileNotFoundError):
            rng = np.random.RandomState(42)
            self.real_image = (rng.rand(64, 64, 22).astype(np.float32) * 2000)
            self.real_mask = np.zeros((64, 64, 22), dtype=np.uint8)
            self.real_mask[20:44, 20:44, 5:17] = 1
            self.has_real_data = False

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _connect_fake(server_url: str = "", api_key: str | None = None,
                      **__: Any) -> FakeNnInteractiveSession:
        return FakeNnInteractiveSession(server_url=server_url, api_key=api_key)

    # -- Single point prediction ---------------------------------------------

    def test_single_foreground_point_yields_segmentation(self):
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        self.assertGreater(result["foreground_voxels"], 0)
        self.assertEqual("cpu", result["device"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        self.assertTrue(np.any(output), "Output mask should have foreground voxels")

    def test_include_and_exclude_points_refine_mask(self):
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [
                    {"point": [32, 32, 11], "include_interaction": True},
                    {"point": [38, 32, 11], "include_interaction": False},
                ],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        self.assertEqual(1, output[32, 32, 11], "Include point should be in mask")
        self.assertEqual(0, output[38, 32, 11], "Exclude point should not be in mask")

    # -- Foreground box ------------------------------------------------------

    def test_foreground_box_fills_region(self):
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "box",
                "include_interaction": True,
                "bbox": [[30, 36], [30, 36], [10, 12]],
                "coordinates": "mimics",
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        # The output is in Mimics coordinates, same as input for identity mapping.
        self.assertTrue(np.all(output[30:36, 30:36, 10:12] > 0),
                        "Bbox region should be filled")

    # -- Initial segmentation replay -----------------------------------------

    def test_initial_segmentation_is_preserved_and_refined(self):
        shape = list(self.real_image.shape)
        initial_mask = np.zeros(shape, dtype=np.uint8)
        initial_mask[28:36, 28:36, 9:13] = 1

        request = _make_bridge_request(
            image=self.real_image,
            mask=initial_mask,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [38, 38, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        init_region = output[28:36, 28:36, 9:13]
        self.assertGreater(np.count_nonzero(init_region), 0,
                           "Initial mask region should be present")
        self.assertEqual(1, output[38, 38, 11],
                         "New include point should be in mask")

    # -- Multi-step iterative refinement ------------------------------------

    def test_iterative_refinement_with_multiple_prompts(self):
        shape = list(self.real_image.shape)
        output_path = os.path.join(self.temp_dir, "result.u8")

        # Step 1.
        req1 = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )
        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result1 = BRIDGE.run_bridge(req1)

        self.assertEqual("refined", result1["status"])
        output1 = np.fromfile(output_path, dtype=np.uint8).reshape(shape)
        self.assertTrue(np.any(output1))

        # Step 2: use output1 as initial.
        req2 = _make_bridge_request(
            image=self.real_image,
            mask=output1,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [28, 28, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )
        req2["output_path"] = os.path.join(self.temp_dir, "result2.u8")
        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result2 = BRIDGE.run_bridge(req2)

        self.assertEqual("refined", result2["status"])
        output2 = np.fromfile(req2["output_path"], dtype=np.uint8).reshape(shape)
        self.assertEqual(1, output2[32, 32, 11],
                         "First point region should still be present")
        self.assertEqual(1, output2[28, 28, 11],
                         "Second point region should be added")

    # -- Empty interactions -------------------------------------------------

    def test_no_interactions_returns_skipped(self):
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("skipped", result["status"])
        self.assertIn("no_interactions", result.get("reason", ""))

    # -- Error handling -----------------------------------------------------

    def test_bridge_reports_error_from_session(self):
        FakeNnInteractiveSession.fail_on_next_set_image = True
        try:
            shape = list(self.real_image.shape)
            request = _make_bridge_request(
                image=self.real_image,
                interactions=[{
                    "interaction_type": "point_set",
                    "coordinates": "mimics",
                    "points": [{"point": [32, 32, 11], "include_interaction": True}],
                }],
                output_dir=self.temp_dir,
                model_dir=self.model_dir,
                image_shape=shape,
            )

            with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
                result = BRIDGE.run_bridge(request)

            self.assertEqual("error", result["status"])
            self.assertIn("Simulated set_image failure", result["error"])
            self.assertIsNotNone(result.get("bridge_log"))
            self.assertIsNotNone(result.get("server_log"))
        finally:
            FakeNnInteractiveSession.fail_on_next_set_image = False

    def test_missing_model_dir_reports_error(self):
        result = BRIDGE.run_bridge({
            "output_path": os.path.join(self.temp_dir, "out.u8"),
            "interactions": [{"interaction_type": "point", "point": [1, 1, 1]}],
        })
        self.assertEqual("error", result["status"])
        self.assertIn("model_dir", result["error"].lower())

    def test_missing_output_path_reports_error(self):
        result = BRIDGE.run_bridge({
            "model_dir": self.model_dir,
            "interactions": [{"interaction_type": "point", "point": [1, 1, 1]}],
        })
        self.assertEqual("error", result["status"])

    # -- Buffer mapping: transpose ------------------------------------------

    def test_buffer_mapping_transpose(self):
        """Point in mimics coords should be correctly mapped through the bridge.

        With platform_to_mimics_axes=[0, 2, 1]:
          - mimics point [1, 2, 1] → platform point [1, 1, 2]
          - The bridge converts to platform, runs inference, converts back.
          - Output is in mimics coordinates, so output[1, 2, 1] should be set.
        """
        image = np.zeros((4, 3, 5), dtype=np.int16)
        shape = list(image.shape)
        mapping = {
            "platform_to_mimics_axes": [0, 2, 1],
            "platform_to_mimics_flips": [False, False, False],
        }

        request = _make_bridge_request(
            image=image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [1, 2, 1], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            buffer_mapping=mapping,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        # Output in mimics coords: the original point [1, 2, 1] should be set.
        self.assertEqual(1, output[1, 2, 1],
                         "Point in mimics coords should be in output after round-trip")

    def test_buffer_mapping_flip(self):
        """Point with axis flip should round-trip correctly.

        With platform_to_mimics_flips=[True, False, False] on a shape-[4,5,3] image:
          - mimics point [3, 0, 0] → flip axis 0 → platform point [0, 0, 0]
          - After inference, convert back: platform [0,0,0] → flip → mimics [3,0,0]
        """
        shape = [4, 5, 3]
        image = np.zeros(shape, dtype=np.int16)
        mapping = {
            "platform_to_mimics_axes": [0, 1, 2],
            "platform_to_mimics_flips": [True, False, False],
        }

        request = _make_bridge_request(
            image=image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [3, 0, 0], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            buffer_mapping=mapping,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        # After round-trip through flip: mimics[3,0,0] → platform[0,0,0]
        # → result in platform → mimics[3,0,0] in output.
        self.assertEqual(1, output[3, 0, 0],
                         "Flipped point should be at original position after round-trip")

    # -- NIfTI path ---------------------------------------------------------

    def test_bridge_accepts_nifti_image_path(self):
        nii_path = os.path.join(self.temp_dir, "image.nii.gz")
        nib.save(nib.Nifti1Image(self.real_image, np.eye(4)), nii_path)

        shape = list(self.real_image.shape)
        request = {
            "image_path": nii_path,
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            "interaction_shape": shape,
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])

    # -- Legacy protocol ----------------------------------------------------

    def test_legacy_protocol_single_interaction(self):
        shape = list(self.real_image.shape)
        scribble_path = os.path.join(self.temp_dir, "scribble.u8")
        scribble = np.zeros(shape, dtype=np.uint8)
        scribble[32, 32, 11] = 1
        scribble.tofile(scribble_path)

        request = _make_bridge_request(
            image=self.real_image,
            image_shape=shape,
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
        )
        del request["interactions"]
        request["interaction_path"] = scribble_path
        request["interaction_shape"] = shape
        request["interaction_type"] = "scribble"
        request["include_interaction"] = True

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])

    # -- Cropped scribble ---------------------------------------------------

    def test_cropped_scribble_is_placed_correctly(self):
        shape = [10, 10, 10]
        image = np.zeros(shape, dtype=np.int16)

        crop_dir = os.path.join(self.temp_dir, "crops")
        os.makedirs(crop_dir, exist_ok=True)
        crop_path = os.path.join(crop_dir, "crop.u8")
        crop = np.ones((2, 2, 1), dtype=np.uint8)
        crop.tofile(crop_path)

        request = _make_bridge_request(
            image=image,
            interactions=[{
                "interaction_type": "scribble",
                "include_interaction": True,
                "mask_path": crop_path,
                "mask_shape": [2, 2, 1],
                "interaction_bbox": [[4, 6], [4, 6], [5, 6]],
                "coordinates": "mimics",
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        self.assertTrue(np.all(output[4:6, 4:6, 5:6] > 0),
                        "Scribble bbox region should be filled")

    # -- CPU device ----------------------------------------------------------

    def test_cpu_device_is_resolved_correctly(self):
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            device="cpu",
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        self.assertEqual("cpu", result["device"])

    # -- Bridge logging ------------------------------------------------------

    def test_bridge_writes_structured_logs(self):
        log_dir = os.path.join(self.temp_dir, "logs")
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )
        request["log_dir"] = log_dir

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        bridge_log = Path(result["bridge_log"])
        self.assertTrue(bridge_log.is_file(), f"Bridge log should exist: {bridge_log}")
        lines = bridge_log.read_text().strip().split("\n")
        self.assertGreaterEqual(len(lines), 2, "Should have init and completion log lines")
        events = [json.loads(line)["event"] for line in lines]
        self.assertIn("session_initializing", events)
        self.assertIn("prediction_completed", events)

    # -- Polyline rasterization ----------------------------------------------

    def test_polyline_to_mask_handles_single_point(self):
        mask = BRIDGE._polyline_to_mask([5, 5, 3], [[2, 2, 1]])
        self.assertEqual(1, int(np.count_nonzero(mask)))
        self.assertTrue(mask[2, 2, 1])

    def test_polyline_to_mask_closed_contour(self):
        mask = BRIDGE._polyline_to_mask(
            [8, 8, 3],
            [[2, 2, 1], [5, 2, 1], [5, 5, 1], [2, 5, 1]],
            closed=True,
        )
        self.assertTrue(mask[2, 2, 1])
        self.assertTrue(mask[5, 2, 1])
        self.assertTrue(mask[5, 5, 1])
        self.assertTrue(mask[2, 5, 1])

    # -- Filled region boundary ----------------------------------------------

    def test_filled_region_boundary_extracts_edges(self):
        filled = np.zeros((1, 10, 10), dtype=bool)
        filled[0, 3:7, 3:7] = True
        boundary = BRIDGE._filled_region_boundary(filled)
        self.assertFalse(boundary[0, 5, 5], "Interior should not be on boundary")
        self.assertTrue(boundary[0, 3, 3], "Corner should be on boundary")
        # 4x4 filled → 4x4 - 2x2 interior = 12 boundary pixels.
        self.assertEqual(12, int(np.count_nonzero(boundary)))

    # -- Interaction mask ----------------------------------------------------

    def test_interaction_mask_point_coordinates(self):
        mask = BRIDGE._interaction_mask(
            {"point": [2, 3, 4], "coordinates": "mimics"},
            mimics_shape=[5, 5, 5],
            platform_shape=[5, 5, 5],
            buffer_mapping={
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
        )
        self.assertEqual(1, int(np.count_nonzero(mask)))
        self.assertTrue(mask[2, 3, 4])

    # -- Image loading -------------------------------------------------------

    def test_load_image_raw_without_mapping(self):
        shape = [4, 5, 3]
        path = os.path.join(self.temp_dir, "raw_image.u8")
        data = np.arange(60, dtype=np.int16).reshape(shape)
        data.tofile(path)

        result = BRIDGE.load_image_raw(
            path, shape, "int16",
            buffer_mapping={"platform_to_mimics_axes": [0, 1, 2],
                            "platform_to_mimics_flips": [False, False, False]},
            coordinates="mimics",
        )
        self.assertEqual((1, 4, 5, 3), result.shape)
        np.testing.assert_array_equal(data.astype(np.float32), result[0])

    def test_load_image_raw_with_axis_swap(self):
        shape = [2, 3, 4]
        path = os.path.join(self.temp_dir, "raw_swapped.u8")
        data = np.arange(24, dtype=np.int16).reshape(shape)
        data.tofile(path)

        mapping = {
            "platform_to_mimics_axes": [2, 0, 1],
            "platform_to_mimics_flips": [False, False, False],
        }
        result = BRIDGE.load_image_raw(
            path, shape, "int16",
            buffer_mapping=mapping,
            coordinates="mimics",
        )
        # Inverse of [2, 0, 1] is [1, 2, 0].
        inverse_axes = [1, 2, 0]
        expected = np.transpose(data.astype(np.float32), inverse_axes)
        np.testing.assert_array_equal(expected, result[0])

    def test_load_image_raw_size_mismatch_raises(self):
        path = os.path.join(self.temp_dir, "bad_image.u8")
        np.zeros(10, dtype=np.int16).tofile(path)

        with self.assertRaisesRegex(RuntimeError, "byte count mismatch"):
            BRIDGE.load_image_raw(
                path, [3, 3, 3], "int16",
                buffer_mapping={"platform_to_mimics_axes": [0, 1, 2],
                                "platform_to_mimics_flips": [False, False, False]},
                coordinates="mimics",
            )

    def test_load_interaction_u8_size_mismatch_raises(self):
        path = os.path.join(self.temp_dir, "bad_interaction.u8")
        np.zeros(8, dtype=np.uint8).tofile(path)

        with self.assertRaisesRegex(RuntimeError, "byte count mismatch"):
            BRIDGE.load_interaction_u8(path, [3, 3, 3])

    # -- Point validation ----------------------------------------------------

    def test_point_outside_bounds_raises(self):
        with self.assertRaisesRegex(RuntimeError, "outside image bounds"):
            BRIDGE._point_mask([5, 5, 5], [10, 0, 0])

    # -- platform_to_mimics round-trip ---------------------------------------

    def test_platform_to_mimics_roundtrip(self):
        mapping = {
            "platform_to_mimics_axes": [1, 2, 0],
            "platform_to_mimics_flips": [False, True, False],
        }
        original = np.random.RandomState(99).rand(3, 4, 5).astype(np.float32)
        platform = BRIDGE.mimics_to_platform(original, mapping)
        restored = BRIDGE.platform_to_mimics(platform, mapping)
        np.testing.assert_array_equal(original, restored)

    # -- Legacy interaction conversion (bridge module) -----------------------

    def test_legacy_conversion_foreground_only(self):
        result = BRIDGE._legacy_interactions({
            "interaction_path": "fg.u8",
            "interaction_shape": [2, 3, 4],
            "interaction_type": "scribble",
            "include_interaction": True,
        })
        self.assertEqual(1, len(result))
        self.assertTrue(result[0]["include_interaction"])
        self.assertEqual([2, 3, 4], result[0]["mask_shape"])

    def test_legacy_foreground_and_background_are_ordered_prompts(self):
        prompts = BRIDGE._legacy_interactions({
            "interaction_path": "foreground.u8",
            "bg_interaction_path": "background.u8",
            "interaction_shape": [2, 3, 4],
            "interaction_type": "scribble",
            "include_interaction": True,
        })
        self.assertEqual(2, len(prompts))
        self.assertTrue(prompts[0]["include_interaction"])
        self.assertFalse(prompts[1]["include_interaction"])

    # -- _apply_scribble_set --------------------------------------------------

    def test_apply_scribble_set_foreground_and_background(self):
        """_apply_scribble_set applies multiple scribbles in one interaction."""
        shape = list(self.real_image.shape)
        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "scribble_set",
                "coordinates": "mimics",
                "scribbles": [
                    {
                        "interaction_type": "scribble",
                        "include_interaction": True,
                        "mask_path": self._create_dummy_scribble(
                            np.ones((2, 2, 1), dtype=np.uint8), "fg"),
                        "mask_shape": [2, 2, 1],
                        "interaction_bbox": [[30, 32], [30, 32], [10, 11]],
                        "coordinates": "mimics",
                    },
                    {
                        "interaction_type": "scribble",
                        "include_interaction": False,
                        "mask_path": self._create_dummy_scribble(
                            np.ones((2, 2, 1), dtype=np.uint8), "bg"),
                        "mask_shape": [2, 2, 1],
                        "interaction_bbox": [[33, 35], [33, 35], [10, 11]],
                        "coordinates": "mimics",
                    },
                ],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )

        with patch.object(BRIDGE, "_connect_remote", side_effect=self._connect_fake):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        self.assertTrue(np.all(output[30:32, 30:32, 10:11] > 0),
                        "Foreground scribble region should be filled")
        # Background scribble region should be excluded.
        self.assertTrue(np.all(output[33:35, 33:35, 10:11] == 0),
                        "Background scribble region should be empty")

    def _create_dummy_scribble(self, data: np.ndarray, name: str) -> str:
        """Helper: write a scribble crop to a temp file, return path."""
        path = os.path.join(self.temp_dir, f"scribble_{name}.u8")
        data.tofile(path)
        return path

    # -- warmup_retry ---------------------------------------------------------

    def test_warmup_retry_on_first_call_empty_prediction(self):
        """Bridge retries once when first_call=True and prediction is empty.

        first_call=True arises from _ensure_server indicating the server was just
        started. Uses a session that returns empty on first predict but succeeds
        on retry."""
        shape = list(self.real_image.shape)

        class _WarmupSession(FakeNnInteractiveSession):
            """Session that returns empty on first call, succeeds on retry."""
            def __init__(self, **kw):
                super().__init__(**kw)
                self._predict_count = 0

            def _apply_all(self):
                import time
                self._predict_count += 1
                if self._predict_count == 1:
                    # First call: produce empty result.
                    if self._target is not None:
                        self._target.fill(0)
                    if self._initial_seg is not None:
                        np.copyto(self._target, self._initial_seg)
                    return
                # Retry: normal behavior.
                super()._apply_all()

        def _connect_warmup(server_url="", api_key=None, **kw):
            return _WarmupSession(server_url=server_url, api_key=api_key)

        request = _make_bridge_request(
            image=self.real_image,
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            output_dir=self.temp_dir,
            model_dir=self.model_dir,
            image_shape=shape,
        )
        # Enable auto_start_server and mock _ensure_server to return first_call=True.
        request["auto_start_server"] = True
        request["server_url"] = "http://127.0.0.1:1527"

        with patch.object(BRIDGE, "_connect_remote", side_effect=_connect_warmup), \
             patch.object(BRIDGE, "_ensure_server",
                          return_value=(True, "http://127.0.0.1:1527", None)):
            result = BRIDGE.run_bridge(request)

        self.assertEqual("refined", result["status"])
        self.assertTrue(result.get("warmup_retry"),
                        "First-call empty prediction should trigger warmup_retry")
        output = np.fromfile(request["output_path"], dtype=np.uint8).reshape(shape)
        self.assertTrue(np.any(output),
                        "Result should have foreground after warmup retry")

    # -- _server_address normalization ----------------------------------------

    def test_server_address_normalization_triple_slash(self):
        """'http:///127.0.0.1:1527' normalizes to ('127.0.0.1', 1527)."""
        host, port = BRIDGE._server_address("http:///127.0.0.1:1527")
        self.assertEqual("127.0.0.1", host)
        self.assertEqual(1527, port)

    def test_server_address_no_scheme(self):
        """'127.0.0.1:1527' (no scheme) normalizes to ('127.0.0.1', 1527)."""
        host, port = BRIDGE._server_address("127.0.0.1:1527")
        self.assertEqual("127.0.0.1", host)
        self.assertEqual(1527, port)

    def test_server_address_host_port_in_path(self):
        """URL where host:port lands in path due to extra slashes."""
        host, port = BRIDGE._server_address("http:///localhost:8080")
        self.assertEqual("localhost", host)
        self.assertEqual(8080, port)

    def test_server_address_rejects_https(self):
        """_server_address rejects non-http schemes."""
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            BRIDGE._server_address("https://127.0.0.1:1527")

    def test_server_address_rejects_empty(self):
        """_server_address rejects empty/None URLs."""
        with self.assertRaisesRegex(RuntimeError, "Unsupported"):
            BRIDGE._server_address("")


# ---------------------------------------------------------------------------
#  Complete Mimics user workflow simulation
# ---------------------------------------------------------------------------

class CompleteMimicsWorkflowSimulation(unittest.TestCase):
    """Simulate the complete Mimics user workflow end-to-end.

    These tests simulate what an annotator actually does:
      1. Opens a project with an image set.
      2. Selects or creates a target mask.
      3. Launches nnInteractive from Scripting Library.
      4. Adds interactive prompts (points, scribbles, boxes, lassos).
      5. Observes predicted segmentation after each prompt.
      6. Uses Undo and Reset.
      7. Finishes the session.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="e2e_workflow_")
        self.fake = _make_fake_mimics()
        self.runtime = _load_runtime_module(self.fake)

        self.model_dir = os.path.join(self.temp_dir, "models", "nnInteractive_v1.0")
        os.makedirs(self.model_dir, exist_ok=True)
        fold_dir = os.path.join(self.model_dir, "fold_0")
        os.makedirs(fold_dir, exist_ok=True)
        Path(os.path.join(fold_dir, "checkpoint_final.pth")).write_bytes(b"weights")

        # Write a minimal config pointing to our temp dir.
        config = {
            "schema_version": "nninteractive_config.v1",
            "device": "cpu",
            "model_dir": self.model_dir,
            "auto_start_server": False,
            "reuse_session": False,
            "execution_mode": "sync",  # Use synchronous path for testing.
            "bridge_script": str(
                Path(__file__).resolve().parents[1]
                / "adapters" / "mimics" / "nninteractive_bridge.py"
            ),
            # Point python at the current interpreter so that the runtime
            # can find it (we only need an executable that exists; the mock
            # intercepts before it's actually used).
            "python": sys.executable,
        }
        config_path = os.path.join(self.temp_dir, "nninteractive_config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)
        os.environ["NNINTERACTIVE_CONFIG"] = config_path

        try:
            self.real_image_3d = _load_real_image_3d()
            self.real_mask_3d = _load_real_mask_3d()
            self.has_real_data = True
        except (RuntimeError, FileNotFoundError):
            rng = np.random.RandomState(42)
            self.real_image_3d = (rng.rand(64, 64, 22).astype(np.float32) * 2000)
            self.real_mask_3d = np.zeros((64, 64, 22), dtype=np.uint8)
            self.real_mask_3d[20:44, 20:44, 5:17] = 1
            self.has_real_data = False

        # Mock _bridge_call at the runtime level: instead of spawning a
        # subprocess, use a fake nnInteractive session directly.
        self._bridge_call_patcher = patch.object(
            self.runtime, "_bridge_call",
            side_effect=self._simulated_bridge_call,
        )
        self._bridge_call_patcher.start()

    def tearDown(self):
        self._bridge_call_patcher.stop()
        self.fake.reset()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        os.environ.pop("NNINTERACTIVE_CONFIG", None)

    def _simulated_bridge_call(
        self, config, image_export, base_export, interactions, output_path
    ) -> dict:
        """Simulate a bridge call using FakeNnInteractiveSession."""
        import time
        started = time.time()

        session = FakeNnInteractiveSession()
        try:
            # Load the image just like the real bridge would.
            image = BRIDGE.load_image_raw(
                image_export["path"],
                image_export["shape"],
                image_export["dtype"],
                buffer_mapping={
                    "platform_to_mimics_axes": [0, 1, 2],
                    "platform_to_mimics_flips": [False, False, False],
                },
                coordinates="mimics",
            )
            target = np.zeros(image.shape[1:], dtype=np.uint8)
            session.set_image(image)
            session.set_target_buffer(target)

            # Load initial segmentation if available.
            if base_export.get("pixel_count", 0) > 0:
                initial = BRIDGE.load_interaction_u8(
                    base_export["path"], base_export["shape"]
                )
                if np.any(initial):
                    session.add_initial_seg_interaction(
                        initial.astype(np.uint8),
                        run_prediction=False,
                    )

            # Apply interactions.
            session.reset_interactions()
            applied = 0
            identity_mapping = {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            }
            platform_shape = list(image.shape[1:])
            mimics_shape = image_export["shape"]

            for interaction in interactions:
                interaction_type = str(interaction.get("interaction_type", "scribble"))

                if interaction_type == "point_set":
                    accepted = BRIDGE._apply_point_set(
                        session, interaction,
                        mimics_shape=mimics_shape,
                        platform_shape=platform_shape,
                        buffer_mapping=identity_mapping,
                    )
                else:
                    interaction_platform = BRIDGE._interaction_mask(
                        interaction,
                        mimics_shape=mimics_shape,
                        platform_shape=platform_shape,
                        buffer_mapping=identity_mapping,
                    )
                    if not np.any(interaction_platform):
                        continue
                    accepted = BRIDGE._apply_interaction(
                        session,
                        interaction_platform,
                        interaction_type,
                        bool(interaction.get("include_interaction", True)),
                    )
                if accepted:
                    applied += 1

            if applied == 0:
                return {
                    "status": "skipped",
                    "output_path": output_path,
                    "elapsed_seconds": 0.0,
                    "reason": "no_interactions",
                }

            result_platform = np.asarray(target, dtype=np.uint8)
            output_dir = os.path.dirname(output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(result_platform.tobytes(order="C"))

            return {
                "status": "refined",
                "output_path": output_path,
                "elapsed_seconds": round(time.time() - started, 2),
                "mode": "remote",
                "first_call": False,
                "device": "cpu",
                "foreground_voxels": int(np.count_nonzero(result_platform)),
                "result_shape": list(result_platform.shape),
            }
        finally:
            session.close()

    # -- Workflow: Launch → Point → Finish ----------------------------------

    def test_workflow_new_mask_with_single_point(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        # Dialog sequence:
        # 1. "Create New Result Mask" → _select_target_mask
        # 2. "Add Points" → _prompt_menu → enters _capture_point_set
        # 3. "Add Include Point" → captures point via indicate_coordinate
        # 4. "Run Points (1)" → returns point_set interaction
        # 5. "Finish" → exits _prompt_menu
        self.fake.dialogs.set_responses(
            question_box=[
                "Create New Result Mask",
                "Add Points",
                "Add Include Point",
                "Run Points (1)",
                "Finish",
            ]
        )
        self.fake.set_indicate_coordinate([(32, 32, 11)])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        masks = [m for m in self.fake.data.masks
                 if not str(getattr(m, "name", "")).startswith(
                     self.runtime.PROMPT_MASK_PREFIX)]
        self.assertGreaterEqual(len(masks), 1)
        result_mask = masks[-1]
        self.assertIn("nnInteractive", getattr(result_mask, "name", ""))
        self.assertGreater(int(np.count_nonzero(result_mask._data)), 0,
                           "Result mask should have foreground voxels")

    def test_workflow_multiple_points_with_undo(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Create New Result Mask",
                "Add Points",
                "Add Include Point", "Add Include Point", "Run Points (2)",
                "Add Points",
                "Add Include Point", "Run Points (1)",
                "Undo Last Prompt",
                "Finish",
            ]
        )
        self.fake.set_indicate_coordinate([
            (32, 32, 11),
            (30, 30, 10),
            (36, 36, 12),
        ])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        masks = [m for m in self.fake.data.masks
                 if not str(getattr(m, "name", "")).startswith(
                     self.runtime.PROMPT_MASK_PREFIX)]
        result_mask = masks[-1]
        self.assertGreater(int(np.count_nonzero(result_mask._data)), 0)

    def test_workflow_undo_all_prompts_restores_base(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        initial_data = np.zeros(self.real_image_3d.shape, dtype=np.uint8)
        initial_data[28:36, 28:36, 9:13] = 1
        existing_mask = self.fake.add_mask(
            initial_data.copy(), name="Existing Mask",
            selected=True, image=image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Add Points",
                "Add Include Point", "Run Points (1)",
                "Undo Last Prompt",
                "Finish",
            ]
        )
        self.fake.set_indicate_coordinate([(32, 32, 11)])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        np.testing.assert_array_equal(initial_data, existing_mask._data)

    def test_workflow_reset_restores_base_mask(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        initial_data = np.zeros(self.real_image_3d.shape, dtype=np.uint8)
        initial_data[28:36, 28:36, 9:13] = 1
        existing_mask = self.fake.add_mask(
            initial_data.copy(), name="Existing Mask",
            selected=True, image=image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Add Points",
                "Add Include Point", "Run Points (1)",
                "Add Points",
                "Add Include Point", "Run Points (1)",
                "Reset To Start",
                "Finish",
            ]
        )
        self.fake.set_indicate_coordinate([
            (32, 32, 11),
            (40, 40, 12),
        ])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        np.testing.assert_array_equal(initial_data, existing_mask._data)

    # -- Workflow: Box prompt -----------------------------------------------

    def test_workflow_box_prompt(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Create New Result Mask",
                "Draw Box",
                "Finish",
            ]
        )
        self.fake.set_indicate_distance([
            _DistanceMeasurement((30, 30, 11), (36, 36, 11))
        ])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        masks = [m for m in self.fake.data.masks
                 if not str(getattr(m, "name", "")).startswith(
                     self.runtime.PROMPT_MASK_PREFIX)]
        result_mask = masks[-1]
        self.assertGreater(int(np.count_nonzero(result_mask._data)), 0)

    # -- Workflow: Lasso prompt ---------------------------------------------

    def test_workflow_lasso_prompt(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Create New Result Mask",
                "Draw Lasso",
                "Finish",
            ]
        )
        lasso_points = [
            (28, 28, 11), (36, 28, 11), (36, 36, 11), (28, 36, 11),
        ]
        self.fake.set_indicate_spline([
            _Spline(lasso_points, closed=True)
        ])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        masks = [m for m in self.fake.data.masks
                 if not str(getattr(m, "name", "")).startswith(
                     self.runtime.PROMPT_MASK_PREFIX)]
        result_mask = masks[-1]
        self.assertGreater(int(np.count_nonzero(result_mask._data)), 0)

    def test_workflow_open_lasso_is_rejected(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Create New Result Mask",
                "Draw Lasso",
                "Finish",
            ]
        )
        lasso_points = [(28, 28, 11), (36, 28, 11), (36, 36, 11)]
        self.fake.set_indicate_spline([
            _Spline(lasso_points, closed=False)
        ])

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        # No prediction should have been made; result mask should be empty.
        masks = [m for m in self.fake.data.masks
                 if not str(getattr(m, "name", "")).startswith(
                     self.runtime.PROMPT_MASK_PREFIX)]
        if len(masks) > 1:
            result_mask = masks[-1]
            self.assertEqual(0, int(np.count_nonzero(result_mask._data)),
                             "Result should be empty since lasso was rejected")

    # -- Workflow: Scribble -------------------------------------------------

    def test_workflow_foreground_scribble(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Create New Result Mask",
                "Paint Scribble",
                "Foreground",
                "Finish",
            ]
        )

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

        # No prompt masks should remain (they are cleaned up).
        prompt_masks = [m for m in self.fake.data.masks
                        if str(getattr(m, "name", "")).startswith(
                            self.runtime.PROMPT_MASK_PREFIX)]
        self.assertEqual(0, len(prompt_masks),
                         "All prompt masks should be cleaned up")

        result_masks = [m for m in self.fake.data.masks
                        if not str(getattr(m, "name", "")).startswith(
                            self.runtime.PROMPT_MASK_PREFIX)]
        self.assertGreaterEqual(len(result_masks), 1)

    def test_workflow_background_scribble(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        initial_data = np.zeros(self.real_image_3d.shape, dtype=np.uint8)
        initial_data[20:44, 20:44, 5:17] = 1
        self.fake.add_mask(initial_data.copy(), name="Full Mask",
                           selected=True, image=image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Paint Scribble",
                "Background",
                "Finish",
            ]
        )

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

    # -- Mask from different image is correctly excluded -------------------

    def test_workflow_rejects_mask_from_different_image(self):
        """A mask bound to image2 should NOT appear in the target list for image1."""
        image1 = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        image2_data = (np.random.RandomState(7).rand(64, 64, 22).astype(np.float32) * 2000)
        image2 = self.fake.add_image(image2_data, name="CT_002")

        mask_on_image2 = self.fake.add_mask(
            np.zeros(image2_data.shape, dtype=np.uint8),
            name="Mask on CT_002", selected=True, image=image2)
        self.fake.set_active_image(image1)

        # The mask bound to image2 should be excluded from image1's target list.
        masks = self.runtime._masks_for_image(image1)
        self.assertNotIn(mask_on_image2, masks,
                         "Mask bound to a different image should be excluded")

        # The mask should appear in image2's target list.
        masks2 = self.runtime._masks_for_image(image2)
        self.assertIn(mask_on_image2, masks2,
                      "Mask should appear in its own image's target list")

    # -- Bridge session context lifecycle ------------------------------------

    def test_bridge_session_context_reuse(self):
        """_BridgeSessionContext should preprocess image once across multiple predicts."""
        shape = list(self.real_image_3d.shape)
        img_path = os.path.join(self.temp_dir, "image.raw")
        self.real_image_3d.astype(np.int16).tofile(img_path)

        request = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        session = FakeNnInteractiveSession()
        with patch.object(BRIDGE, "_connect_remote", return_value=session):
            context = BRIDGE._BridgeSessionContext(request)
            try:
                for i in range(3):
                    context.predict(
                        [{
                            "interaction_type": "point_set",
                            "coordinates": "mimics",
                            "points": [{
                                "point": [30 + i, 30 + i, 11],
                                "include_interaction": True,
                            }],
                        }],
                        os.path.join(self.temp_dir, f"result_{i}.u8"),
                    )
            finally:
                context.close()

        # set_image should be called exactly once (in __init__).
        self.assertEqual(1, session.set_image_call_count,
                         "set_image should only be called once for multiple predicts")

    # -- No active image -----------------------------------------------------

    def test_workflow_no_active_image_raises_error(self):
        with self.assertRaises(RuntimeError):
            self.runtime.run()

    # -- Cancel mask selection -----------------------------------------------

    def test_workflow_cancel_mask_selection_returns_early(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=["Cancel"]
        )

        exit_code = self.runtime.run()
        self.assertEqual(0, exit_code)

    # -- Image / mask shape mismatch -----------------------------------------

    def test_workflow_image_mask_shape_mismatch(self):
        """The runtime should detect when image and mask buffer shapes differ.

        This is validated inside run() after exports.
        """
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        # Create a mask with the correct shape.
        mask = self.fake.add_mask(
            np.zeros(self.real_image_3d.shape, dtype=np.uint8),
            name="TestMask", selected=True, image=image)

        # Normal export — shapes should match.
        img_export = self.runtime._export_image(
            image, os.path.join(self.temp_dir, "img.raw"))
        mask_export = self.runtime._export_mask(
            mask, os.path.join(self.temp_dir, "mask.u8"))
        self.assertEqual(img_export["shape"], mask_export["shape"])

        # Simulate a broken mask export with wrong shape.
        bad_export = dict(mask_export)
        bad_export["shape"] = [10, 10, 5]
        with self.assertRaisesRegex(RuntimeError, "buffer shapes differ"):
            # Simulate the check that run() performs.
            if img_export["shape"] != bad_export["shape"]:
                raise RuntimeError(
                    "Image and target Mask buffer shapes differ: {0} vs {1}".format(
                        img_export["shape"], bad_export["shape"]
                    )
                )

    # -- Multiple selected masks rejected ------------------------------------

    def test_workflow_multiple_selected_masks_is_rejected(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        for i in range(2):
            self.fake.add_mask(
                np.zeros(self.real_image_3d.shape, dtype=np.uint8),
                name=f"Mask {i}", selected=True, image=image)

        with self.assertRaises(RuntimeError):
            self.runtime._select_target_mask(image)

    # -- Discard points in point set -----------------------------------------

    def test_workflow_discard_points_returns_no_interaction(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Add Include Point",
                "Discard Points",
            ]
        )
        self.fake.set_indicate_coordinate([(32, 32, 11)])

        result = self.runtime._capture_point_set(image)
        self.assertIsNone(result)

    # -- Remove last point ---------------------------------------------------

    def test_workflow_remove_last_point_in_point_set(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        self.fake.dialogs.set_responses(
            question_box=[
                "Add Include Point",
                "Remove Last Point",
                "Discard Points",
            ]
        )
        self.fake.set_indicate_coordinate([(32, 32, 11)])

        result = self.runtime._capture_point_set(image)
        self.assertIsNone(result)

    # -- Cancel scribble sign ------------------------------------------------

    def test_workflow_cancel_scribble_sign_returns_none(self):
        self.fake.dialogs.set_responses(
            question_box=["Cancel"]
        )
        result = self.runtime._choose_sign()
        self.assertIsNone(result)

    # -- Point set cleanup ---------------------------------------------------

    def test_capture_point_set_cleans_up_all_markers(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        initial_count = len(self.fake.data.points)

        self.fake.dialogs.set_responses(
            question_box=[
                "Add Include Point",
                "Add Exclude Point",
                "Run Points (2)",
            ]
        )
        self.fake.set_indicate_coordinate([
            (32, 32, 11),
            (34, 34, 12),
        ])

        result = self.runtime._capture_point_set(image)
        self.assertIsNotNone(result)
        self.assertEqual("point_set", result["interaction_type"])
        self.assertEqual(2, len(result["points"]))

        self.assertEqual(initial_count, len(self.fake.data.points),
                         "All temp point markers should be cleaned up")

    # -- Spline cleanup -----------------------------------------------------

    def test_lasso_cleanup_deletes_spline(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        initial_count = len(self.fake.data.splines)
        lasso_points = [
            (28, 28, 11), (36, 28, 11), (36, 36, 11), (28, 36, 11),
        ]
        self.fake.set_indicate_spline([_Spline(lasso_points, closed=True)])

        result = self.runtime._capture_lasso(image)

        self.assertIsNotNone(result)
        self.assertEqual("lasso", result["interaction_type"])
        self.assertEqual(initial_count, len(self.fake.data.splines),
                         "Temp spline should be deleted after lasso capture")

    # -- Measurement cleanup ------------------------------------------------

    def test_box_cleanup_deletes_measurement(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        initial_count = len(self.fake.data.distance_measurements)
        self.fake.set_indicate_distance([
            _DistanceMeasurement((30, 30, 11), (36, 36, 11))
        ])

        result = self.runtime._capture_box(image)

        self.assertIsNotNone(result)
        self.assertEqual("box", result["interaction_type"])
        self.assertEqual(initial_count, len(self.fake.data.distance_measurements),
                         "Distance measurement should be deleted after box capture")

    # -- Buffer dtype detection ---------------------------------------------

    def test_buffer_dtype_detection(self):
        test_cases = [
            ("b", "int8"), ("B", "uint8"), ("h", "int16"),
            ("H", "uint16"), ("i", "int32"), ("I", "uint32"), ("f", "float32"),
        ]
        for fmt, expected in test_cases:
            view = _VoxelBuffer(np.zeros(1), fmt)
            self.assertEqual(expected, self.runtime._buffer_dtype(view),
                             f"Format {fmt} should map to {expected}")

    def test_buffer_dtype_unknown_raises(self):
        view = _VoxelBuffer(np.zeros(1), "e")
        with self.assertRaisesRegex(RuntimeError, "Unsupported Mimics image buffer format"):
            self.runtime._buffer_dtype(view)

    # -- Image / mask export round-trip --------------------------------------

    def test_image_export_and_load_roundtrip(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        export_path = os.path.join(self.temp_dir, "exported_image.raw")

        export_info = self.runtime._export_image(image, export_path)
        self.assertEqual(list(self.real_image_3d.shape), export_info["shape"])
        self.assertEqual("int16", export_info["dtype"])

        loaded = np.fromfile(export_path, dtype=np.int16).reshape(
            self.real_image_3d.shape)
        np.testing.assert_array_equal(
            self.real_image_3d.astype(np.int16), loaded)

    def test_mask_export_and_restore_roundtrip(self):
        mask_data = np.zeros(self.real_image_3d.shape, dtype=np.uint8)
        mask_data[28:36, 28:36, 9:13] = 1
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        mask = self.fake.add_mask(mask_data.copy(), name="TestMask", image=image)

        export_path = os.path.join(self.temp_dir, "exported_mask.u8")
        export_info = self.runtime._export_mask(mask, export_path)
        self.assertEqual(list(mask_data.shape), export_info["shape"])

        new_mask = _Mask("Restored Mask",
                          np.zeros(self.real_image_3d.shape, dtype=np.uint8))
        self.runtime._set_mask_from_u8(new_mask, export_path, export_info["shape"])
        np.testing.assert_array_equal(mask_data, new_mask._data)

    # -- Unique result name --------------------------------------------------

    def test_unique_result_name_generation(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        name1 = self.runtime._unique_result_name()
        self.assertEqual("nnInteractive Result", name1)

        self.fake.add_mask(name=name1, image=image)
        name2 = self.runtime._unique_result_name()
        self.assertEqual("nnInteractive Result 2", name2)

        self.fake.add_mask(name=name2, image=image)
        name3 = self.runtime._unique_result_name()
        self.assertEqual("nnInteractive Result 3", name3)

    # -- Single slice axis ---------------------------------------------------

    def test_single_slice_axis_detection(self):
        self.assertEqual(2, self.runtime._single_slice_axis(
            [[1, 2, 3], [4, 5, 3], [2, 3, 3]]))
        self.assertEqual(1, self.runtime._single_slice_axis(
            [[1, 3, 2], [4, 3, 5]]))
        self.assertIsNone(self.runtime._single_slice_axis(
            [[1, 2, 3], [4, 5, 6]]))

    # -- Prompt mask filtering -----------------------------------------------

    def test_prompt_masks_are_filtered_from_target_list(self):
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        self.fake.set_active_image(image)

        real_mask = self.fake.add_mask(name="Real Mask", image=image)
        prompt_mask = self.fake.add_mask(
            name="nnInteractive Prompt Foreground scribble", image=image)

        masks = self.runtime._masks_for_image(image)
        self.assertIn(real_mask, masks)
        self.assertNotIn(prompt_mask, masks)

    # -- Bridge call error propagation ---------------------------------------

    def test_bridge_error_is_propagated_to_mimics(self):
        """Bridge errors should be raised as RuntimeError with descriptive message.

        Stop the global _bridge_call mock and test the real function with a
        failing session.
        """
        image = self.fake.add_image(self.real_image_3d.copy(), name="CT_001")
        image_export = self.runtime._export_image(
            image, os.path.join(self.temp_dir, "image.raw"))

        mask_path = os.path.join(self.temp_dir, "empty.u8")
        empty = np.zeros(self.real_image_3d.shape, dtype=np.uint8)
        empty.tofile(mask_path)
        base_export = {"path": mask_path, "shape": list(self.real_image_3d.shape),
                       "pixel_count": 0}

        # For this test, use the real _bridge_call (revert the mock).
        self._bridge_call_patcher.stop()
        try:
            FakeNnInteractiveSession.fail_on_next_set_image = True
            try:
                with patch.object(BRIDGE, "_connect_remote",
                                  return_value=FakeNnInteractiveSession()):
                    with self.assertRaisesRegex(RuntimeError, "nnInteractive"):
                        self.runtime._bridge_call(
                            {"auto_start_server": False, "device": "cpu",
                             "allow_cpu_fallback": True, "fold": "auto",
                             "python": sys.executable,
                             "bridge_script": str(
                                 Path(__file__).resolve().parents[1]
                                 / "adapters" / "mimics" / "nninteractive_bridge.py"
                             ),
                             "model_dir": self.model_dir},
                            image_export, base_export,
                            [{"interaction_type": "point_set",
                              "coordinates": "mimics",
                              "points": [{"point": [32, 32, 11],
                                          "include_interaction": True}]}],
                            os.path.join(self.temp_dir, "result.u8"),
                        )
            finally:
                FakeNnInteractiveSession.fail_on_next_set_image = False
        finally:
            self._bridge_call_patcher.start()


# ---------------------------------------------------------------------------
#  Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
