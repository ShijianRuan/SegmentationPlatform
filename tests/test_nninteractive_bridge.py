from __future__ import annotations

import unittest
import importlib.util
import os
import sys
import types
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

BRIDGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "adapters"
    / "mimics"
    / "nninteractive_bridge.py"
)
BRIDGE_SPEC = importlib.util.spec_from_file_location(
    "mimics_nninteractive_bridge_under_test", BRIDGE_PATH
)
assert BRIDGE_SPEC is not None and BRIDGE_SPEC.loader is not None
BRIDGE = importlib.util.module_from_spec(BRIDGE_SPEC)
BRIDGE_SPEC.loader.exec_module(BRIDGE)

_filled_region_boundary = BRIDGE._filled_region_boundary
_legacy_interactions = BRIDGE._legacy_interactions
_polyline_to_mask = BRIDGE._polyline_to_mask
_interaction_mask = BRIDGE._interaction_mask
run_bridge = BRIDGE.run_bridge


def load_mimics_runtime_module(fake_mimics: object) -> object:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "adapters"
        / "mimics"
        / "runtime_py35"
        / "nninteractive_mimics.py"
    )
    spec = importlib.util.spec_from_file_location(
        "nninteractive_mimics_under_test", module_path
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


class NnInteractiveBridgeTests(unittest.TestCase):
    def test_missing_spline_geometry_is_an_explicit_error(self) -> None:
        module = load_mimics_runtime_module(types.SimpleNamespace())

        with self.assertRaisesRegex(RuntimeError, "without geometry_points or points"):
            module._spline_geometry(types.SimpleNamespace())

    def test_unknown_mimics_buffer_dtype_is_rejected(self) -> None:
        module = load_mimics_runtime_module(types.SimpleNamespace())

        with self.assertRaisesRegex(RuntimeError, "Unsupported Mimics image buffer format"):
            module._buffer_dtype(types.SimpleNamespace(format="e"))

    def test_sibling_environment_is_discovered_for_a_worklist(self) -> None:
        module = load_mimics_runtime_module(types.SimpleNamespace())
        with TemporaryDirectory() as directory:
            root = Path(directory)
            worklist = root / "batch_001"
            runtime = worklist / "runtime_py35"
            runtime.mkdir(parents=True)
            (worklist / "worklist_manifest.json").write_text("{}", encoding="utf-8")
            environment = root / "nninteractive_env"
            python_exe = environment / "python" / "python.exe"
            python_exe.parent.mkdir(parents=True)
            python_exe.write_bytes(b"python")

            with patch.object(module, "__file__", str(runtime / "nninteractive_mimics.py")):
                self.assertEqual(str(environment), module._environment_root())

    def test_scribble_cancel_returns_to_prompt_menu(self) -> None:
        class UserInterrupted(Exception):
            pass

        def cancel_spline(**_kwargs: object) -> None:
            raise UserInterrupted("cancelled")

        fake_mimics = types.SimpleNamespace(
            UserInterrupted=UserInterrupted,
            analyze=types.SimpleNamespace(indicate_spline=cancel_spline),
            data=types.SimpleNamespace(
                splines=types.SimpleNamespace(
                    delete=lambda _spline: self.fail(
                        "No Spline should be deleted when creation was cancelled"
                    )
                )
            ),
        )
        module = load_mimics_runtime_module(fake_mimics)

        result = module._capture_scribble(
            types.SimpleNamespace(get_voxel_indexes=lambda value: value),
            True,
        )

        self.assertIsNone(result)

    def test_polyline_rasterization_keeps_endpoints_and_path(self) -> None:
        mask = _polyline_to_mask([6, 6, 2], [[1, 1, 0], [4, 4, 0]])

        self.assertTrue(mask[1, 1, 0])
        self.assertTrue(mask[2, 2, 0])
        self.assertTrue(mask[3, 3, 0])
        self.assertTrue(mask[4, 4, 0])
        self.assertEqual(4, int(np.count_nonzero(mask)))

    def test_lasso_filled_region_becomes_closed_boundary(self) -> None:
        filled = np.zeros((1, 7, 7), dtype=bool)
        filled[0, 1:6, 1:6] = True

        boundary = _filled_region_boundary(filled)

        self.assertTrue(boundary[0, 1, 1])
        self.assertTrue(boundary[0, 5, 5])
        self.assertFalse(boundary[0, 3, 3])
        self.assertEqual(16, int(np.count_nonzero(boundary)))

    def test_cropped_prompt_is_restored_to_full_mimics_grid(self) -> None:
        with TemporaryDirectory() as directory:
            crop_path = Path(directory) / "crop.u8"
            np.ones((1, 2, 2), dtype=np.uint8).tofile(crop_path)

            restored = _interaction_mask(
                {
                    "interaction_type": "lasso",
                    "mask_path": str(crop_path),
                    "mask_shape": [1, 2, 2],
                    "interaction_bbox": [[2, 3], [1, 3], [3, 5]],
                    "coordinates": "mimics",
                },
                mimics_shape=[5, 5, 6],
                platform_shape=[5, 5, 6],
                buffer_mapping={
                    "platform_to_mimics_axes": [0, 1, 2],
                    "platform_to_mimics_flips": [False, False, False],
                },
            )

        self.assertEqual(4, int(np.count_nonzero(restored)))
        self.assertTrue(restored[2, 1, 3])
        self.assertTrue(restored[2, 2, 4])

    def test_legacy_foreground_and_background_are_ordered_prompts(self) -> None:
        prompts = _legacy_interactions(
            {
                "interaction_path": "foreground.u8",
                "bg_interaction_path": "background.u8",
                "interaction_shape": [2, 3, 4],
                "interaction_type": "scribble",
                "include_interaction": True,
            }
        )

        self.assertEqual(2, len(prompts))
        self.assertTrue(prompts[0]["include_interaction"])
        self.assertFalse(prompts[1]["include_interaction"])
        self.assertEqual([2, 3, 4], prompts[1]["mask_shape"])

    def test_bridge_replays_initial_segmentation_and_ordered_prompts(self) -> None:
        class FakeSession:
            license = "test-license"

            def set_image(self, image: np.ndarray) -> None:
                self.image = image

            def set_target_buffer(self, target: np.ndarray) -> None:
                self.target = target

            def add_initial_seg_interaction(
                self, initial: np.ndarray, run_prediction: bool = False
            ) -> None:
                self.target[:] = initial

            def add_point_interaction(
                self, point: tuple[int, int, int], include_interaction: bool
            ) -> None:
                self.target[point] = 1 if include_interaction else 0

            def close(self) -> None:
                return None

        with TemporaryDirectory() as directory:
            root = Path(directory)
            shape = [4, 4, 1]
            image_path = root / "image.raw"
            initial_path = root / "initial.u8"
            output_path = root / "result.u8"
            np.zeros(shape, dtype=np.int16).tofile(image_path)
            initial = np.zeros(shape, dtype=np.uint8)
            initial[0, 0, 0] = 1
            initial.tofile(initial_path)

            with (
                patch.object(
                    BRIDGE,
                    "_ensure_server",
                    return_value=(False, "http://127.0.0.1:1527", "test-api-key"),
                ),
                patch.object(BRIDGE, "_connect_remote", return_value=FakeSession()),
            ):
                result = run_bridge(
                    {
                        "image_buffer_path": str(image_path),
                        "image_buffer_shape": shape,
                        "image_buffer_dtype": "int16",
                        "image_buffer_coordinates": "mimics",
                        "initial_seg_path": str(initial_path),
                        "initial_seg_shape": shape,
                        "interactions": [
                            {
                                "interaction_type": "point",
                                "include_interaction": True,
                                "point": [2, 2, 0],
                                "coordinates": "mimics",
                            },
                            {
                                "interaction_type": "point",
                                "include_interaction": False,
                                "point": [0, 0, 0],
                                "coordinates": "mimics",
                            },
                        ],
                        "buffer_mapping": {
                            "platform_to_mimics_axes": [0, 1, 2],
                            "platform_to_mimics_flips": [False, False, False],
                        },
                        "output_path": str(output_path),
                        "model_dir": str(root),
                        "device": "cpu",
                    }
                )

            output = np.fromfile(output_path, dtype=np.uint8).reshape(shape)
            self.assertEqual("refined", result["status"])
            self.assertEqual(2, result["interaction_count"])
            self.assertEqual("test-license", result["model_license"])
            self.assertEqual(0, int(output[0, 0, 0]))
            self.assertEqual(1, int(output[2, 2, 0]))

    def test_stale_pid_record_never_terminates_an_unrelated_process(self) -> None:
        signals = []

        def record_kill(pid: int, sig: int) -> None:
            signals.append((pid, sig))

        state = {
            "pid": os.getpid(),
            "model_dir": "/tmp/model",
            "ownership_token": "not-in-command-line",
        }
        with (
            patch.object(BRIDGE, "_process_command_line", return_value="python unrelated.py"),
            patch.object(BRIDGE.os, "kill", side_effect=record_kill),
        ):
            self.assertFalse(BRIDGE._terminate_owned_server(state))

        self.assertEqual([(os.getpid(), 0)], signals)

    def test_portable_windows_server_script_uses_relative_paths(self) -> None:
        build_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "build_nninteractive_bundle.py"
        )
        spec = importlib.util.spec_from_file_location("bundle_builder_under_test", build_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with TemporaryDirectory() as directory, patch.object(module.sys, "platform", "win32"):
            build_root = Path(directory)
            module.create_activation_scripts(build_root)
            content = (
                build_root / "nninteractive_env" / "start_server.bat"
            ).read_text(encoding="ascii")

        self.assertIn('set "ROOT=%~dp0"', content)
        self.assertIn('set "PYTHON=%ROOT%python\\python.exe"', content)
        self.assertNotIn(str(build_root), content)

    def test_setup_repairs_partial_environment_without_deleting_weights(self) -> None:
        setup_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "setup_nninteractive_env.py"
        )
        spec = importlib.util.spec_from_file_location("nninteractive_setup_under_test", setup_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / "nninteractive_env"
            weights = environment / "models" / "nnInteractive_v1.0" / "checkpoint_final.pth"
            weights.parent.mkdir(parents=True)
            weights.write_bytes(b"weights")
            module.PROJECT_ROOT = root
            module.ENV_DIR = environment
            module.VENV_PYTHON = environment / "bin" / "python"

            def fake_run(command: list[str], **_kwargs: object) -> types.SimpleNamespace:
                if command[1:3] == ["-m", "venv"]:
                    module.VENV_PYTHON.parent.mkdir(parents=True, exist_ok=True)
                    module.VENV_PYTHON.write_bytes(b"python")
                return types.SimpleNamespace(returncode=0)

            with patch.object(module, "run", side_effect=fake_run):
                module.create_venv()

            self.assertTrue(module.VENV_PYTHON.is_file())
            self.assertEqual(b"weights", weights.read_bytes())


if __name__ == "__main__":
    unittest.main()
