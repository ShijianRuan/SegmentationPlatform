# -*- coding: utf-8 -*-
"""Subprocess-level integration tests for the nnInteractive bridge.

These tests spawn the actual bridge script as a subprocess (the way Mimics
does) and communicate via JSON over stdin/stdout. A fake nnInteractive
package is injected via PYTHONPATH so that the bridge can import and use
a controlled fake session.

This tests the REAL communication protocol, not a mocked version of it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
#  Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "adapters" / "mimics" / "nninteractive_bridge.py"

# ---------------------------------------------------------------------------
#  Build a fake nnInteractive package for the bridge process to import.
# ---------------------------------------------------------------------------


def _build_fake_nninteractive_package(target_dir: str) -> str:
    """Create a minimal fake nnInteractive package that the bridge can import.

    Returns the site-packages directory to add to PYTHONPATH.
    """
    pkg = Path(target_dir) / "nnInteractive"
    inference = pkg / "inference"
    inference.mkdir(parents=True, exist_ok=True)

    (pkg / "__init__.py").write_text("")
    (inference / "__init__.py").write_text("")

    # Write the fake remote module.
    (inference / "remote.py").write_text(
        '''# Fake nnInteractive remote inference session for subprocess testing.
import json, os, sys, time, traceback
import numpy as np
from scipy.ndimage import binary_dilation, binary_fill_holes


class nnInteractiveRemoteInferenceSession:
    """Fake remote session used by the bridge subprocess."""

    def __init__(self, server_url="", api_key=None,
                 read_timeout=1800, set_image_read_timeout=1800,
                 write_timeout=600):
        self.server_url = server_url
        self.api_key = api_key
        self.license = "subprocess-test-license"
        self._image = None
        self._target = None
        self._initial_seg = None
        self._interactions = []

    def set_image(self, image):
        self._image = image.astype(np.float32, copy=True)

    def set_target_buffer(self, target):
        self._target = target

    def reset_interactions(self):
        if self._target is not None:
            self._target.fill(0)
        self._interactions = []

    def add_initial_seg_interaction(self, initial, run_prediction=False):
        self._initial_seg = initial.astype(np.uint8, copy=True)
        if self._target is not None:
            np.copyto(self._target, initial)

    def add_point_interaction(self, point, include_interaction=True,
                               run_prediction=True):
        self._interactions.append({
            "type": "point", "point": point,
            "include": include_interaction,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def add_bbox_interaction(self, bbox, include_interaction=True,
                              run_prediction=True):
        self._interactions.append({
            "type": "bbox", "bbox": bbox, "include": include_interaction,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def add_scribble_interaction(self, crop, include_interaction=True,
                                  run_prediction=True, interaction_bbox=None):
        self._interactions.append({
            "type": "scribble" if include_interaction else "bg_scribble",
            "crop": crop.astype(bool, copy=True),
            "bbox": interaction_bbox,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def add_lasso_interaction(self, crop, include_interaction=True,
                               run_prediction=True, interaction_bbox=None):
        self._interactions.append({
            "type": "lasso", "crop": crop.astype(bool, copy=True),
            "bbox": interaction_bbox,
        })
        if run_prediction and self._target is not None:
            self._apply_all()

    def close(self):
        pass

    # -- internal --
    def _apply_all(self):
        if self._target is None or self._image is None:
            return
        if self._initial_seg is not None:
            np.copyto(self._target, self._initial_seg)
        else:
            self._target.fill(0)
        for ix in self._interactions:
            if ix["type"] == "point":
                p = ix["point"]
                inc = ix["include"]
                if all(0 <= p[d] < self._target.shape[d] for d in range(3)):
                    r = 3
                    sl = tuple(
                        slice(max(0, p[d]-r), min(self._target.shape[d], p[d]+r+1))
                        for d in range(3))
                    if inc:
                        self._target[sl] = 1
                    else:
                        self._target[sl] = 0
            elif ix["type"] == "bbox":
                sl = tuple(
                    slice(int(ix["bbox"][d][0]), int(ix["bbox"][d][1]))
                    for d in range(3))
                self._target[sl] = 1
            elif ix["type"] in ("scribble", "lasso"):
                bbox = ix.get("bbox")
                if bbox is not None:
                    sl = tuple(
                        slice(int(bbox[d][0]), int(bbox[d][1]))
                        for d in range(3))
                    expanded = binary_dilation(ix["crop"], iterations=3)
                    if ix["type"] == "scribble":
                        self._target[sl] = np.logical_or(
                            self._target[sl], expanded)
                    else:
                        filled = binary_fill_holes(
                            binary_dilation(ix["crop"], iterations=1))
                        self._target[sl] = np.logical_or(
                            self._target[sl], filled)
        if np.any(self._target):
            result = binary_dilation(self._target, iterations=1)
            result = binary_fill_holes(result)
            np.copyto(self._target, result.astype(np.uint8))
'''
    )

    # Also write a fake inference_session module for local mode.
    (inference / "inference_session.py").write_text(
        '''# Stub — local inference is not used in subprocess tests.
class nnInteractiveInferenceSession:
    def __init__(self, **kw):
        raise RuntimeError("Local inference not available in test")
'''
    )

    # Write server.main stub so the bridge can handle --watchdog references.
    server_dir = pkg / "inference" / "server"
    server_dir.mkdir(parents=True, exist_ok=True)
    (pkg / "inference" / "server" / "__init__.py").write_text("")
    (server_dir / "main.py").write_text(
        '''# Stub server main — not used in tests.
if __name__ == "__main__":
    print("fake server")
'''
    )

    return str(Path(target_dir))


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _bridge_subprocess(request: dict, *, env: dict | None = None,
                        timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the bridge script as a subprocess with the given JSON request."""
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    return subprocess.run(
        [sys.executable, str(BRIDGE_SCRIPT)],
        input=json.dumps(request).encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        env=proc_env,
    )


def _worker_subprocess(requests: list[dict], *, env: dict | None = None,
                        timeout: int = 60) -> subprocess.CompletedProcess:
    """Run the bridge in --worker mode, feeding multiple JSON lines."""
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    stdin_data = "\n".join(json.dumps(r, separators=(",", ":"))
                           for r in requests) + "\n"
    return subprocess.run(
        [sys.executable, str(BRIDGE_SCRIPT), "--worker"],
        input=stdin_data.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        env=proc_env,
    )


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------


class SubprocessBridgeTests(unittest.TestCase):
    """Test the real bridge subprocess communication."""

    @classmethod
    def setUpClass(cls):
        cls.fake_pkg_dir = tempfile.mkdtemp(prefix="fake_nni_")
        _build_fake_nninteractive_package(cls.fake_pkg_dir)
        cls.base_env = {"PYTHONPATH": cls.fake_pkg_dir,
                        "NN_INTERACTIVE_API_KEY": "subprocess-test-key"}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fake_pkg_dir, ignore_errors=True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="sp_bridge_")
        self.model_dir = os.path.join(self.temp_dir, "models", "nnInteractive_v1.0")
        os.makedirs(self.model_dir, exist_ok=True)
        fold_dir = os.path.join(self.model_dir, "fold_0")
        os.makedirs(fold_dir, exist_ok=True)
        Path(os.path.join(fold_dir, "checkpoint_final.pth")).write_bytes(b"weights")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_request(self, image_shape=None, interactions=None, **overrides):
        shape = image_shape or [64, 64, 22]
        img = (np.random.RandomState(99).rand(*shape).astype(np.float32) * 2000)
        img_path = os.path.join(self.temp_dir, "image.raw")
        img.astype(np.int16).tofile(img_path)
        output_path = os.path.join(self.temp_dir, "result.u8")

        req = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": interactions or [],
            "output_path": output_path,
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
            "log_dir": os.path.join(self.temp_dir, "logs"),
        }
        req.update(overrides)
        return req

    # -- Basic subprocess round-trip -----------------------------------------

    def test_subprocess_single_point_prediction(self):
        """Bridge subprocess: single include point → refined result."""
        req = self._make_request(interactions=[{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": [32, 32, 11], "include_interaction": True}],
        }])

        proc = _bridge_subprocess(req, env=self.base_env)

        self.assertEqual(0, proc.returncode,
                         f"stderr: {proc.stderr.decode()}")
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])
        self.assertGreater(result["foreground_voxels"], 0)
        # Output file must exist and have content.
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        self.assertTrue(np.any(output))

    def test_subprocess_include_and_exclude_points(self):
        """Bridge subprocess: include + exclude points."""
        req = self._make_request(interactions=[{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [
                {"point": [32, 32, 11], "include_interaction": True},
                {"point": [38, 32, 11], "include_interaction": False},
            ],
        }])

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        self.assertEqual(1, output[32, 32, 11])
        self.assertEqual(0, output[38, 32, 11])

    def test_subprocess_box_interaction(self):
        """Bridge subprocess: bbox fills the specified region."""
        req = self._make_request(interactions=[{
            "interaction_type": "box",
            "include_interaction": True,
            "bbox": [[30, 36], [30, 36], [10, 12]],
            "coordinates": "mimics",
        }])

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        self.assertTrue(np.all(output[30:36, 30:36, 10:12] > 0))

    def test_subprocess_initial_segmentation_replay(self):
        """Bridge subprocess: initial mask + new point → both in result."""
        shape = [64, 64, 22]
        initial = np.zeros(shape, dtype=np.uint8)
        initial[28:36, 28:36, 9:13] = 1
        init_path = os.path.join(self.temp_dir, "initial.u8")
        initial.tofile(init_path)

        req = self._make_request(interactions=[{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": [38, 38, 11], "include_interaction": True}],
        }])
        req["initial_seg_path"] = init_path
        req["initial_seg_shape"] = shape

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(shape)
        self.assertGreater(np.count_nonzero(output[28:36, 28:36, 9:13]), 0,
                           "Initial mask region preserved")
        self.assertEqual(1, output[38, 38, 11])

    def test_subprocess_empty_interactions_skipped(self):
        """Bridge subprocess: no interactions → skipped status."""
        req = self._make_request(interactions=[])

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("skipped", result["status"])

    # -- Error paths through the subprocess -----------------------------------

    def test_subprocess_missing_model_dir_returns_error(self):
        """Bridge subprocess: with auto_start_server=False, model_dir is only
        needed for the server lifecycle, not for inference. The bridge should
        succeed if a session is provided and log_dir is writable.

        However, without log_dir and with unwritable model_dir parent, the
        log creation fails → error.
        """
        req = self._make_request()
        req["model_dir"] = "/nonexistent/path"
        # Remove log_dir so the bridge tries model_dir parent for logs → fails.
        req.pop("log_dir", None)
        req["interactions"] = [{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": [32, 32, 11], "include_interaction": True}],
        }]

        proc = _bridge_subprocess(req, env=self.base_env)
        result = json.loads(proc.stdout.decode())
        # The model_dir parent (/nonexistent) is on a read-only filesystem,
        # so log creation fails. The bridge catches this and returns error.
        self.assertEqual("error", result["status"])
        self.assertIsNotNone(result.get("error"))

    def test_subprocess_invalid_json_input_returns_error(self):
        """Bridge subprocess: invalid JSON stdin → error status."""
        proc = subprocess.run(
            [sys.executable, str(BRIDGE_SCRIPT)],
            input=b"not valid json {{{",
            capture_output=True,
            timeout=30,
            env=self.base_env,
        )
        self.assertEqual(2, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("error", result["status"])
        self.assertIn("Invalid JSON", result["error"])

    def test_subprocess_missing_image_buffer_returns_error(self):
        """Bridge subprocess: no image data → error."""
        req = {
            "interactions": [{
                "interaction_type": "point",
                "point": [1, 1, 1],
            }],
            "output_path": os.path.join(self.temp_dir, "out.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(2, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("error", result["status"])
        self.assertIn("image", result["error"].lower())

    def test_subprocess_nifti_image_path(self):
        """Bridge subprocess: NIfTI image instead of raw buffer."""
        import nibabel as nib
        shape = [64, 64, 22]
        img = np.random.RandomState(42).rand(*shape).astype(np.float32) * 2000
        nii_path = os.path.join(self.temp_dir, "image.nii.gz")
        nib.save(nib.Nifti1Image(img, np.eye(4)), nii_path)

        req = {
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

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])

    # -- Buffer mapping through subprocess ------------------------------------

    def test_subprocess_buffer_mapping_transpose(self):
        """Bridge subprocess: axis swap mapping round-trips through subprocess."""
        shape = [4, 3, 5]
        img = np.zeros(shape, dtype=np.int16)
        img_path = os.path.join(self.temp_dir, "image.raw")
        img.tofile(img_path)

        req = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 2, 1],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [1, 2, 1], "include_interaction": True}],
            }],
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(shape)
        self.assertEqual(1, output[1, 2, 1],
                         "Point in mimics coords should survive round-trip")

    def test_subprocess_buffer_mapping_flip(self):
        """Bridge subprocess: axis flip mapping round-trips through subprocess."""
        shape = [4, 5, 3]
        img = np.zeros(shape, dtype=np.int16)
        img_path = os.path.join(self.temp_dir, "image.raw")
        img.tofile(img_path)

        req = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [True, False, False],
            },
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [3, 0, 0], "include_interaction": True}],
            }],
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(shape)
        self.assertEqual(1, output[3, 0, 0],
                         "Flipped point should be at original mimic position")

    # -- Bridge logging -------------------------------------------------------

    def test_subprocess_writes_bridge_logs(self):
        """Bridge subprocess: JSONL log files are written."""
        req = self._make_request(interactions=[{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": [32, 32, 11], "include_interaction": True}],
        }])

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)

        result = json.loads(proc.stdout.decode())
        log_path = Path(result["bridge_log"])
        self.assertTrue(log_path.is_file(), f"Log should exist: {log_path}")
        lines = log_path.read_text().strip().split("\n")
        self.assertGreaterEqual(len(lines), 2)
        events = [json.loads(l)["event"] for l in lines]
        self.assertIn("session_initializing", events)
        self.assertIn("prediction_completed", events)

    # -- Legacy protocol through subprocess -----------------------------------

    def test_subprocess_legacy_interaction_protocol(self):
        """Bridge subprocess: legacy interaction_path format."""
        shape = [64, 64, 22]
        scribble_path = os.path.join(self.temp_dir, "scribble.u8")
        scribble = np.zeros(shape, dtype=np.uint8)
        scribble[32, 32, 11] = 1
        scribble.tofile(scribble_path)

        req = self._make_request()
        del req["interactions"]
        req["interaction_path"] = scribble_path
        req["interaction_shape"] = shape
        req["interaction_type"] = "scribble"
        req["include_interaction"] = True

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("refined", result["status"])

    # -- Device resolution in subprocess --------------------------------------

    def test_subprocess_respects_cpu_device(self):
        """Bridge subprocess: explicit CPU device is reported."""
        req = self._make_request(
            interactions=[{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            device="cpu",
        )

        proc = _bridge_subprocess(req, env=self.base_env)
        self.assertEqual(0, proc.returncode)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("cpu", result["device"])


class SubprocessWorkerModeTests(unittest.TestCase):
    """Test the bridge --worker mode (persistent process, JSON-lines protocol).

    The Mimics runtime uses this when ``reuse_session: true`` (the default).
    A single worker process handles multiple predict requests without
    reloading the image.
    """

    @classmethod
    def setUpClass(cls):
        cls.fake_pkg_dir = tempfile.mkdtemp(prefix="fake_nni_worker_")
        _build_fake_nninteractive_package(cls.fake_pkg_dir)
        cls.base_env = {"PYTHONPATH": cls.fake_pkg_dir}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fake_pkg_dir, ignore_errors=True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="sp_worker_")
        self.model_dir = os.path.join(self.temp_dir, "models", "nnInteractive_v1.0")
        os.makedirs(self.model_dir, exist_ok=True)
        fold_dir = os.path.join(self.model_dir, "fold_0")
        os.makedirs(fold_dir, exist_ok=True)
        Path(os.path.join(fold_dir, "checkpoint_final.pth")).write_bytes(b"weights")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _init_request(self) -> dict:
        shape = [64, 64, 22]
        img = np.random.RandomState(77).rand(*shape).astype(np.float32) * 2000
        img_path = os.path.join(self.temp_dir, "image.raw")
        img.astype(np.int16).tofile(img_path)

        return {
            "action": "initialize",
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
            "log_dir": os.path.join(self.temp_dir, "logs"),
        }

    def _predict_request(self, output_idx: int = 0) -> dict:
        return {
            "action": "predict",
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [30 + output_idx, 30 + output_idx, 11],
                            "include_interaction": True}],
            }],
            "output_path": os.path.join(self.temp_dir,
                                         f"result_{output_idx}.u8"),
        }

    def _close_request(self) -> dict:
        return {"action": "close"}

    def test_worker_initialize_predict_close(self):
        """Worker mode: initialize → predict → close lifecycle."""
        requests = [
            self._init_request(),
            self._predict_request(0),
            self._close_request(),
        ]

        proc = _worker_subprocess(requests, env=self.base_env)
        lines = proc.stdout.decode().strip().split("\n")

        # Line 1: initialize → ready.
        r1 = json.loads(lines[0])
        self.assertEqual("ready", r1["status"])
        self.assertEqual("cpu", r1["device"])

        # Line 2: predict → refined.
        r2 = json.loads(lines[1])
        self.assertEqual("refined", r2["status"])
        self.assertGreater(r2.get("foreground_voxels", 0), 0)

        # Line 3: close → closed.
        r3 = json.loads(lines[2])
        self.assertEqual("closed", r3["status"])

        # Verify output file.
        output = np.fromfile(
            requests[1]["output_path"], dtype=np.uint8
        ).reshape([64, 64, 22])
        self.assertTrue(np.any(output))

    def test_worker_multiple_predictions_reuse_image(self):
        """Worker mode: multiple predict calls reuse the preloaded image."""
        requests = [
            self._init_request(),
            self._predict_request(0),
            self._predict_request(1),
            self._predict_request(2),
            self._close_request(),
        ]

        proc = _worker_subprocess(requests, env=self.base_env)
        lines = proc.stdout.decode().strip().split("\n")
        self.assertEqual(5, len(lines))

        for i in range(3):
            r = json.loads(lines[1 + i])
            self.assertEqual("refined", r["status"],
                             f"Prediction {i} should be refined")

    def test_worker_predict_without_initialize_fails(self):
        """Worker mode: predict before initialize → error."""
        requests = [
            self._predict_request(0),
            self._close_request(),
        ]

        proc = _worker_subprocess(requests, env=self.base_env)
        lines = proc.stdout.decode().strip().split("\n")
        r1 = json.loads(lines[0])
        self.assertEqual("error", r1["status"])

    def test_worker_unknown_action_fails(self):
        """Worker mode: unsupported action → error."""
        requests = [
            self._init_request(),
            {"action": "unknown_action"},
            self._close_request(),
        ]

        proc = _worker_subprocess(requests, env=self.base_env)
        lines = proc.stdout.decode().strip().split("\n")
        self.assertEqual(3, len(lines))
        r2 = json.loads(lines[1])
        self.assertEqual("error", r2["status"])

    def test_worker_close_without_initialize(self):
        """Worker mode: close without init should work (no-op)."""
        requests = [self._close_request()]

        proc = _worker_subprocess(requests, env=self.base_env)
        lines = proc.stdout.decode().strip().split("\n")
        r1 = json.loads(lines[0])
        self.assertEqual("closed", r1["status"])

    def test_worker_empty_interactions_skipped(self):
        """Worker mode: predict with no interactions → skipped."""
        init = self._init_request()
        predict = {
            "action": "predict",
            "interactions": [],
            "output_path": os.path.join(self.temp_dir, "result_skip.u8"),
        }
        requests = [init, predict, self._close_request()]

        proc = _worker_subprocess(requests, env=self.base_env)
        lines = proc.stdout.decode().strip().split("\n")
        r2 = json.loads(lines[1])
        self.assertEqual("skipped", r2["status"])


class SubprocessBridgeErrorHandlingTests(unittest.TestCase):
    """Test the bridge's error handling when things go wrong."""

    @classmethod
    def setUpClass(cls):
        cls.fake_pkg_dir = tempfile.mkdtemp(prefix="fake_nni_err_")
        _build_fake_nninteractive_package(cls.fake_pkg_dir)
        cls.base_env = {"PYTHONPATH": cls.fake_pkg_dir}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.fake_pkg_dir, ignore_errors=True)

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="sp_err_")
        self.model_dir = os.path.join(self.temp_dir, "models", "nnInteractive_v1.0")
        os.makedirs(self.model_dir, exist_ok=True)
        fold_dir = os.path.join(self.model_dir, "fold_0")
        os.makedirs(fold_dir, exist_ok=True)
        Path(os.path.join(fold_dir, "checkpoint_final.pth")).write_bytes(b"weights")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_image_buffer_byte_count_mismatch(self):
        """Bridge subprocess: wrong buffer size → error."""
        shape = [64, 64, 22]
        img_path = os.path.join(self.temp_dir, "image.raw")
        # Write wrong number of bytes.
        np.zeros([10, 10, 5], dtype=np.int16).tofile(img_path)

        req = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,  # Shape says 64x64x22 but file is smaller.
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        proc = _bridge_subprocess(req, env=self.base_env)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("error", result["status"])
        self.assertIn("byte count mismatch", result["error"])

    def test_interaction_buffer_byte_count_mismatch(self):
        """Bridge subprocess: wrong interaction mask size → error."""
        shape = [64, 64, 22]
        img = np.random.RandomState(42).rand(*shape).astype(np.float32) * 2000
        img_path = os.path.join(self.temp_dir, "image.raw")
        img.astype(np.int16).tofile(img_path)

        # Create a scribble mask with wrong size.
        scribble_path = os.path.join(self.temp_dir, "scribble.u8")
        np.zeros([10, 10, 5], dtype=np.uint8).tofile(scribble_path)

        req = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": [{
                "interaction_type": "scribble",
                "include_interaction": True,
                "mask_path": scribble_path,
                "mask_shape": [64, 64, 22],  # Shape says 64x64x22 but file is 10x10x5.
                "coordinates": "mimics",
            }],
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }

        proc = _bridge_subprocess(req, env=self.base_env)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("error", result["status"])
        self.assertIn("byte count mismatch", result["error"])

    def test_unknown_interaction_type_raises(self):
        """Bridge subprocess: unsupported interaction type → error."""
        req = self._make_base_request()
        req["interactions"] = [{
            "interaction_type": "unknown_type",
            "coordinates": "mimics",
            "points": [{"point": [32, 32, 11], "include_interaction": True}],
        }]

        proc = _bridge_subprocess(req, env=self.base_env)
        result = json.loads(proc.stdout.decode())
        self.assertEqual("error", result["status"])

    def _make_base_request(self):
        shape = [64, 64, 22]
        img = np.random.RandomState(42).rand(*shape).astype(np.float32) * 2000
        img_path = os.path.join(self.temp_dir, "image.raw")
        img.astype(np.int16).tofile(img_path)

        return {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": [],
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": self.model_dir,
            "device": "cpu",
            "server_url": "http://127.0.0.1:1527",
            "auto_start_server": False,
        }


if __name__ == "__main__":
    unittest.main()
