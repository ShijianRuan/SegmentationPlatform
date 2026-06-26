# -*- coding: utf-8 -*-
"""Real nnInteractive inference tests via HTTP remote mode.

These tests use the ACTUAL nnInteractive HTTP server (127.0.0.1:1527)
with REAL model weights (392 MB checkpoint). The full production data flow:

  1. Bridge script spawned as subprocess (real subprocess communication)
  2. Bridge connects to nnInteractive HTTP server (real remote session)
  3. Server runs real inference with the trained model on CPU
  4. Bridge writes prediction result as .u8 buffer

This is the SAME mode used in production — the only difference is that
Mimics Research 21 runs on Windows, while these tests run on macOS.

CPU inference is slow (~7 min / prediction on 64³ volumes).
Run with:  pytest test_nninteractive_real_inference.py -v --timeout=3600
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

import nibabel as nib
import numpy as np

# ---------------------------------------------------------------------------
#  Paths & config
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SCRIPT = PROJECT_ROOT / "adapters" / "mimics" / "nninteractive_bridge.py"
MODEL_DIR = str(
    PROJECT_ROOT / "nninteractive_env" / "models" / "nnInteractive_v1.0"
)
SERVER_URL = "http://127.0.0.1:1527"
SERVER_API_KEY = "test-real-api-key"
REAL_DATA_DIR = Path("/Users/ruanshijian/Downloads/datasets/synthstrip_data_v1.5")

# System proxy on macOS interferes with httpx connecting to localhost.
# Bypass it for all subprocess calls.
_NO_PROXY_ENV = {
    "no_proxy": "localhost,127.0.0.1,*.local,0.0.0.0",
    "NO_PROXY": "localhost,127.0.0.1,*.local,0.0.0.0",
    "NN_INTERACTIVE_API_KEY": SERVER_API_KEY,
}

# CPU prediction timeout — generous for the first call (model compilation).
_PREDICTION_TIMEOUT = 3600  # 1 hour


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _load_real_image_3d(case: str = "asl_epi_101") -> np.ndarray:
    path = REAL_DATA_DIR / case / "image.nii.gz"
    return np.asarray(nib.load(str(path)).dataobj, dtype=np.float32)


def _load_real_mask_3d(case: str = "asl_epi_101") -> np.ndarray:
    path = REAL_DATA_DIR / case / "mask.nii.gz"
    return np.asarray(nib.load(str(path)).dataobj, dtype=np.uint8)


def _mask_foreground_center(mask: np.ndarray) -> tuple[int, int, int] | None:
    nonzero = np.argwhere(mask)
    if len(nonzero) == 0:
        return None
    return tuple(int(round(c)) for c in nonzero.mean(axis=0))


def _bridge_subprocess(request: dict, timeout: int = _PREDICTION_TIMEOUT) -> dict:
    """Run the bridge script as a subprocess with the real server.

    The subprocess inherits no_proxy to bypass the system HTTP proxy.
    """
    proc_env = os.environ.copy()
    proc_env.update(_NO_PROXY_ENV)

    proc = subprocess.run(
        [sys.executable, str(BRIDGE_SCRIPT)],
        input=json.dumps(request).encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        env=proc_env,
    )
    result = json.loads(proc.stdout.decode())
    result["_stderr"] = proc.stderr.decode("utf-8", "replace")
    result["_returncode"] = proc.returncode
    return result


def _worker_subprocess(requests: list[dict],
                        timeout: int = _PREDICTION_TIMEOUT) -> subprocess.CompletedProcess:
    """Run the bridge in --worker mode against the real server."""
    proc_env = os.environ.copy()
    proc_env.update(_NO_PROXY_ENV)

    stdin_data = "\n".join(
        json.dumps(r, separators=(",", ":")) for r in requests
    ) + "\n"

    return subprocess.run(
        [sys.executable, str(BRIDGE_SCRIPT), "--worker"],
        input=stdin_data.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        env=proc_env,
    )


def _check_server() -> None:
    """Verify the nnInteractive server is reachable."""
    proc_env = os.environ.copy()
    proc_env.update(_NO_PROXY_ENV)
    r = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         f"{SERVER_URL}/healthz"],
        capture_output=True, text=True, timeout=10,
        env=proc_env,
    )
    if r.stdout.strip() != "200":
        raise RuntimeError(
            f"nnInteractive server not reachable at {SERVER_URL}. "
            f"Start it first:\n"
            f"  python -m nnInteractive.inference.server.main \\\n"
            f"    --model-dir {MODEL_DIR} \\\n"
            f"    --host 127.0.0.1 --port 1527 --device cpu \\\n"
            f"    --max-sessions 5 --api-key {SERVER_API_KEY}"
        )


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    Path(MODEL_DIR, "fold_0", "checkpoint_final.pth").is_file(),
    "Model weights not downloaded.",
)
class RealRemoteBridgeTests(unittest.TestCase):
    """Bridge subprocess → real nnInteractive HTTP server → real model.

    These are the most realistic tests possible without actual Mimics.
    Each prediction takes ~7 minutes on CPU.
    """

    @classmethod
    def setUpClass(cls):
        _check_server()
        ckpt = Path(MODEL_DIR, "fold_0", "checkpoint_final.pth")
        print(f"\n✓ Model: {ckpt.stat().st_size / 1024**2:.0f} MB")

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="real_remote_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_request(self, image: np.ndarray, interactions: list,
                       **overrides) -> dict:
        shape = list(image.shape)
        img_path = os.path.join(self.temp_dir, "image.raw")
        image.astype(np.int16).tofile(img_path)

        req = {
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "interactions": interactions,
            "output_path": os.path.join(self.temp_dir, "result.u8"),
            "model_dir": MODEL_DIR,
            "device": "cpu",
            "server_url": SERVER_URL,
            "auto_start_server": False,
            "prediction_timeout_seconds": _PREDICTION_TIMEOUT,
            "set_image_timeout_seconds": _PREDICTION_TIMEOUT,
            "log_dir": os.path.join(self.temp_dir, "logs"),
        }
        req.update(overrides)
        return req

    # -- Single point prediction (real server, real model) --------------------

    def test_remote_single_point_produces_segmentation(self):
        """HTTP remote: single include point → model produces segmentation."""
        image = _load_real_image_3d()
        req = self._make_request(image, [{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": [32, 32, 11], "include_interaction": True}],
        }])

        t0 = time.time()
        result = _bridge_subprocess(req)
        elapsed = time.time() - t0

        stderr = result.pop("_stderr", "")
        self.assertEqual("refined", result["status"],
                         f"stderr: {stderr[:500]}")
        self.assertGreater(result["foreground_voxels"], 0)
        self.assertEqual("cpu", result["device"])
        self.assertEqual("remote", result["mode"])

        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        self.assertTrue(np.any(output))
        print(f"\n  foreground={result['foreground_voxels']}, "
              f"elapsed={elapsed:.0f}s, mode={result['mode']}")

    def test_remote_include_and_exclude_points(self):
        """HTTP remote: include + exclude points."""
        image = _load_real_image_3d()
        req = self._make_request(image, [{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [
                {"point": [32, 32, 11], "include_interaction": True},
                {"point": [38, 32, 11], "include_interaction": False},
            ],
        }])

        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"],
                         f"Error: {result.get('_stderr', '')[:500]}")
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        self.assertTrue(np.any(output))
        self.assertEqual(1, output[32, 32, 11],
                         "Include point should be foreground")

    def test_remote_initial_mask_with_additional_point(self):
        """HTTP remote: start from GT mask + add point → high Dice overlap."""
        image = _load_real_image_3d()
        gt_mask = _load_real_mask_3d()
        center = _mask_foreground_center(gt_mask)
        self.assertIsNotNone(center)

        init_path = os.path.join(self.temp_dir, "initial.u8")
        gt_mask.tofile(init_path)

        req = self._make_request(image, [{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": list(center), "include_interaction": True}],
        }])
        req["initial_seg_path"] = init_path
        req["initial_seg_shape"] = list(gt_mask.shape)

        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"],
                         f"Error: {result.get('_stderr', '')[:500]}")
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        # Dice overlap with ground truth.
        intersection = np.count_nonzero(np.logical_and(output, gt_mask))
        union = np.count_nonzero(np.logical_or(output, gt_mask))
        dice = (2 * intersection / (union + intersection)
                if (union + intersection) > 0 else 0)
        print(f"\n  Dice with GT: {dice:.3f}")
        self.assertGreater(dice, 0.3,
                           f"Output should overlap with GT (Dice={dice:.3f})")

    # -- Box interaction ------------------------------------------------------

    def test_remote_box_interaction(self):
        """HTTP remote: 2D bbox (single slice) → model fills the region."""
        image = _load_real_image_3d()
        req = self._make_request(image, [{
            "interaction_type": "box",
            "include_interaction": True,
            "bbox": [[28, 36], [28, 36], [11, 12]],  # z-slice 11 only
            "coordinates": "mimics",
        }])

        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"],
                         f"Error: {result.get('_stderr', '')[:500]}")
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        region = output[28:36, 28:36, 11:12]
        fg_ratio = np.count_nonzero(region) / region.size
        print(f"\n  Box region fg ratio: {fg_ratio:.2f}")
        self.assertGreater(fg_ratio, 0.2,
                           f"Box region should have foreground (ratio={fg_ratio:.2f})")

    # -- Lasso interaction ----------------------------------------------------

    def test_remote_lasso_interaction(self):
        """HTTP remote: closed 2D lasso → model fills interior."""
        image = _load_real_image_3d()
        req = self._make_request(image, [{
            "interaction_type": "lasso",
            "include_interaction": True,
            "polyline_points": [
                [28, 28, 11], [36, 28, 11], [36, 36, 11], [28, 36, 11],
            ],
            "polyline_closed": True,
            "coordinates": "mimics",
        }])

        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"],
                         f"Error: {result.get('_stderr', '')[:500]}")
        output = np.fromfile(req["output_path"], dtype=np.uint8).reshape(
            req["image_buffer_shape"])
        self.assertGreater(np.count_nonzero(output), 0)

    # -- Scribble via crop ----------------------------------------------------

    def test_remote_scribble_interaction(self):
        """HTTP remote: scribble mask crop → model produces foreground."""
        image = _load_real_image_3d()
        crop_dir = os.path.join(self.temp_dir, "crops")
        os.makedirs(crop_dir, exist_ok=True)
        crop_path = os.path.join(crop_dir, "crop.u8")
        np.ones((2, 2, 1), dtype=np.uint8).tofile(crop_path)

        req = self._make_request(image, [{
            "interaction_type": "scribble",
            "include_interaction": True,
            "mask_path": crop_path,
            "mask_shape": [2, 2, 1],
            "interaction_bbox": [[30, 32], [30, 32], [10, 11]],
            "coordinates": "mimics",
        }])

        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"],
                         f"Error: {result.get('_stderr', '')[:500]}")
        self.assertGreater(result["foreground_voxels"], 0)

    # -- Empty interactions ---------------------------------------------------

    def test_remote_empty_interactions_skipped(self):
        """HTTP remote: no interactions → skipped."""
        image = _load_real_image_3d()
        req = self._make_request(image, [])
        result = _bridge_subprocess(req)
        self.assertEqual("skipped", result["status"])

    # -- Bridge logging -------------------------------------------------------

    def test_remote_bridge_writes_structured_logs(self):
        """HTTP remote: bridge produces JSONL logs."""
        image = _load_real_image_3d()
        req = self._make_request(image, [{
            "interaction_type": "point_set",
            "coordinates": "mimics",
            "points": [{"point": [32, 32, 11], "include_interaction": True}],
        }])

        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"])

        log_path = Path(result["bridge_log"])
        self.assertTrue(log_path.is_file())
        lines = log_path.read_text().strip().split("\n")
        self.assertGreaterEqual(len(lines), 2)
        events = [json.loads(l)["event"] for l in lines]
        self.assertIn("session_initializing", events)
        self.assertIn("prediction_completed", events)

    # -- Device reporting -----------------------------------------------------

    def test_remote_cpu_device_reported(self):
        """HTTP remote: CPU device correctly reported."""
        image = _load_real_image_3d()
        req = self._make_request(
            image, [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            device="cpu",
        )
        result = _bridge_subprocess(req)
        self.assertEqual("refined", result["status"])
        self.assertEqual("cpu", result["device"])
        self.assertEqual("remote", result["mode"])


@unittest.skipUnless(
    Path(MODEL_DIR, "fold_0", "checkpoint_final.pth").is_file(),
    "Model weights not downloaded.",
)
class RealRemoteWorkerTests(unittest.TestCase):
    """Worker mode (--worker) against the real HTTP server."""

    @classmethod
    def setUpClass(cls):
        _check_server()

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="real_worker_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_remote_worker_full_lifecycle(self):
        """HTTP remote worker: initialize → predict → predict → close."""
        image = _load_real_image_3d()
        shape = list(image.shape)
        img_path = os.path.join(self.temp_dir, "image.raw")
        image.astype(np.int16).tofile(img_path)

        init = {
            "action": "initialize",
            "image_buffer_path": img_path,
            "image_buffer_shape": shape,
            "image_buffer_dtype": "int16",
            "image_buffer_coordinates": "mimics",
            "buffer_mapping": {
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
            "model_dir": MODEL_DIR,
            "device": "cpu",
            "server_url": SERVER_URL,
            "auto_start_server": False,
            "prediction_timeout_seconds": _PREDICTION_TIMEOUT,
            "set_image_timeout_seconds": _PREDICTION_TIMEOUT,
            "log_dir": os.path.join(self.temp_dir, "logs"),
        }

        predict1 = {
            "action": "predict",
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [32, 32, 11], "include_interaction": True}],
            }],
            "output_path": os.path.join(self.temp_dir, "result1.u8"),
        }

        predict2 = {
            "action": "predict",
            "interactions": [{
                "interaction_type": "point_set",
                "coordinates": "mimics",
                "points": [{"point": [28, 28, 11], "include_interaction": True}],
            }],
            "output_path": os.path.join(self.temp_dir, "result2.u8"),
        }

        close = {"action": "close"}

        proc = _worker_subprocess([init, predict1, predict2, close])

        lines = proc.stdout.decode().strip().split("\n")
        self.assertEqual(4, len(lines),
                         f"Expected 4 responses, got {len(lines)}")

        r1 = json.loads(lines[0])
        self.assertEqual("ready", r1["status"],
                         f"Init failed: {r1.get('error', '')[:200]}")
        self.assertIn("server_url", r1,
                      "Init should return server_url")
        # Note: "mode" is only present in predict responses, not in ready.

        for i in range(2):
            r = json.loads(lines[1 + i])
            self.assertEqual("refined", r["status"],
                             f"Predict {i} failed: {r.get('error', '')[:200]}")
            self.assertGreater(r.get("foreground_voxels", 0), 0)
            out = np.fromfile(
                [predict1, predict2][i]["output_path"], dtype=np.uint8
            ).reshape(shape)
            self.assertTrue(np.any(out))

        r4 = json.loads(lines[3])
        self.assertEqual("closed", r4["status"])


if __name__ == "__main__":
    unittest.main()
