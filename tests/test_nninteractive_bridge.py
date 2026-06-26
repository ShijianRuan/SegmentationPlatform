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
    def test_device_auto_and_cuda_fallback_use_cpu_without_cuda(self) -> None:
        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: False)
        )
        with patch.dict(sys.modules, {"torch": fake_torch}):
            self.assertEqual(
                ("cpu", "CUDA is unavailable; nnInteractive will run on CPU."),
                BRIDGE._resolve_device("auto"),
            )
            device, warning = BRIDGE._resolve_device("cuda:0")

        self.assertEqual("cpu", device)
        self.assertIn("falling back to CPU", warning)

    def test_single_available_fold_is_not_forced_to_all(self) -> None:
        with TemporaryDirectory() as directory:
            model = Path(directory)
            fold = model / "fold_0"
            fold.mkdir()
            (fold / "checkpoint_final.pth").write_bytes(b"weights")

            self.assertIsNone(BRIDGE._resolve_fold(str(model), "auto"))
            self.assertEqual("0", BRIDGE._resolve_fold(str(model), "all"))

    def test_occupied_default_port_uses_a_free_local_port(self) -> None:
        class FakeSocket:
            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def bind(self, _address: object) -> None:
                return None

            def getsockname(self) -> tuple[str, int]:
                return ("127.0.0.1", 24567)

        with (
            patch.object(BRIDGE, "_port_open", return_value=True),
            patch.object(BRIDGE.socket, "socket", return_value=FakeSocket()),
        ):
            result = BRIDGE._available_server_url("http://127.0.0.1:1527")

        self.assertEqual("http://127.0.0.1:24567", result)

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

    def test_runtime_probe_rejects_an_incomplete_external_python(self) -> None:
        module = load_mimics_runtime_module(types.SimpleNamespace())

        class Process:
            returncode = 0

            def communicate(self, timeout: int) -> tuple[bytes, bytes]:
                return (
                    b'{"python":"C:/Python313/python.exe","version":[3,13,0],'
                    b'"missing":["torch","nnInteractive"]}',
                    b"",
                )

        with patch.object(module.subprocess, "Popen", return_value=Process()):
            with self.assertRaisesRegex(
                RuntimeError,
                "missing required packages: torch, nnInteractive",
            ):
                module._probe_python("C:/Python313/python.exe", 30)

    def test_lasso_cancel_returns_to_prompt_menu(self) -> None:
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

        result = module._capture_lasso(
            types.SimpleNamespace(get_voxel_indexes=lambda value: value)
        )

        self.assertIsNone(result)

    def test_closed_spline_becomes_planar_foreground_lasso(self) -> None:
        deleted = []
        spline = types.SimpleNamespace(
            closed=True,
            geometry_points=[
                (1, 1, 0),
                (4, 1, 0),
                (4, 4, 0),
                (1, 4, 0),
            ],
        )
        fake_mimics = types.SimpleNamespace(
            UserInterrupted=RuntimeError,
            analyze=types.SimpleNamespace(indicate_spline=lambda **_kwargs: spline),
            data=types.SimpleNamespace(
                splines=types.SimpleNamespace(delete=lambda value: deleted.append(value))
            ),
            dialogs=types.SimpleNamespace(
                message_box=lambda *_args, **_kwargs: self.fail(
                    "A valid closed planar Lasso must not show an error"
                )
            ),
        )
        module = load_mimics_runtime_module(fake_mimics)

        result = module._capture_lasso(
            types.SimpleNamespace(get_voxel_indexes=lambda value: value)
        )

        self.assertEqual("lasso", result["interaction_type"])
        self.assertTrue(result["include_interaction"])
        self.assertTrue(result["polyline_closed"])
        self.assertEqual(4, len(result["polyline_points"]))
        self.assertEqual([spline], deleted)

    def test_open_spline_is_rejected_as_lasso(self) -> None:
        messages = []
        spline = types.SimpleNamespace(
            closed=False,
            geometry_points=[(1, 1, 0), (4, 1, 0), (4, 4, 0)],
        )
        fake_mimics = types.SimpleNamespace(
            UserInterrupted=RuntimeError,
            analyze=types.SimpleNamespace(indicate_spline=lambda **_kwargs: spline),
            data=types.SimpleNamespace(
                splines=types.SimpleNamespace(delete=lambda _value: None)
            ),
            dialogs=types.SimpleNamespace(
                message_box=lambda message, **_kwargs: messages.append(message)
            ),
        )
        module = load_mimics_runtime_module(fake_mimics)

        result = module._capture_lasso(
            types.SimpleNamespace(get_voxel_indexes=lambda value: value)
        )

        self.assertIsNone(result)
        self.assertIn("must be closed", messages[0])

    def test_distance_measurement_becomes_positive_2d_box(self) -> None:
        deleted = []
        measurement = types.SimpleNamespace(point1=(1, 2, 3), point2=(4, 6, 3))
        fake_mimics = types.SimpleNamespace(
            UserInterrupted=RuntimeError,
            measure=types.SimpleNamespace(
                indicate_distance_measurement=lambda **_kwargs: measurement
            ),
            data=types.SimpleNamespace(
                distance_measurements=types.SimpleNamespace(
                    delete=lambda value: deleted.append(value)
                )
            ),
            dialogs=types.SimpleNamespace(
                message_box=lambda *_args, **_kwargs: self.fail(
                    "A valid diagonal must not show an error"
                )
            ),
        )
        module = load_mimics_runtime_module(fake_mimics)

        result = module._capture_box(
            types.SimpleNamespace(get_voxel_indexes=lambda value: value)
        )

        self.assertEqual([[1, 5], [2, 7], [3, 4]], result["bbox"])
        self.assertTrue(result["include_interaction"])
        self.assertEqual([measurement], deleted)

    def test_point_set_can_mix_include_and_exclude_before_prediction(self) -> None:
        responses = iter(
            [
                "Add Include Point",
                "Add Exclude Point",
                "Run Points (2)",
            ]
        )
        coordinates = iter([(1, 1, 0), (3, 3, 0)])
        markers = []
        deleted = []

        def create_point(**_kwargs: object) -> object:
            marker = object()
            markers.append(marker)
            return marker

        fake_mimics = types.SimpleNamespace(
            UserInterrupted=RuntimeError,
            dialogs=types.SimpleNamespace(
                question_box=lambda **_kwargs: next(responses)
            ),
            indicate_coordinate=lambda **_kwargs: next(coordinates),
            analyze=types.SimpleNamespace(create_point=create_point),
            data=types.SimpleNamespace(
                points=types.SimpleNamespace(delete=lambda marker: deleted.append(marker))
            ),
        )
        module = load_mimics_runtime_module(fake_mimics)

        result = module._capture_point_set(
            types.SimpleNamespace(get_voxel_indexes=lambda value: value)
        )

        self.assertEqual("point_set", result["interaction_type"])
        self.assertEqual(
            [
                {"point": [1, 1, 0], "include_interaction": True},
                {"point": [3, 3, 0], "include_interaction": False},
            ],
            result["points"],
        )
        self.assertEqual(markers, deleted)

    def test_scribble_uses_ellipse_edit_mask(self) -> None:
        module = load_mimics_runtime_module(types.SimpleNamespace())
        sentinel = {"interaction_type": "scribble"}
        with patch.object(
            module,
            "_capture_mask_prompt",
            return_value=sentinel,
        ) as capture:
            result = module._capture_scribble("image", False, "temp")

        self.assertIs(sentinel, result)
        capture.assert_called_once_with(
            "image",
            False,
            "scribble",
            "Ellipse",
            "temp",
        )

    def test_polyline_rasterization_keeps_endpoints_and_path(self) -> None:
        mask = _polyline_to_mask([6, 6, 2], [[1, 1, 0], [4, 4, 0]])

        self.assertTrue(mask[1, 1, 0])
        self.assertTrue(mask[2, 2, 0])
        self.assertTrue(mask[3, 3, 0])
        self.assertTrue(mask[4, 4, 0])
        self.assertEqual(4, int(np.count_nonzero(mask)))

        closed = _polyline_to_mask(
            [6, 6, 2],
            [[1, 1, 0], [4, 1, 0], [4, 4, 0]],
            closed=True,
        )
        self.assertTrue(closed[1, 1, 0])
        self.assertTrue(closed[2, 2, 0])
        self.assertTrue(closed[3, 3, 0])

    def test_lasso_filled_region_becomes_closed_boundary(self) -> None:
        filled = np.zeros((1, 7, 7), dtype=bool)
        filled[0, 1:6, 1:6] = True

        boundary = _filled_region_boundary(filled)

        self.assertTrue(boundary[0, 1, 1])
        self.assertTrue(boundary[0, 5, 5])
        self.assertFalse(boundary[0, 3, 3])
        self.assertEqual(16, int(np.count_nonzero(boundary)))

    def test_multislice_scribble_predicts_only_after_last_slice(self) -> None:
        calls = []

        class Session:
            def add_scribble_interaction(
                self,
                crop: np.ndarray,
                include_interaction: bool,
                run_prediction: bool,
                interaction_bbox: list[list[int]],
            ) -> None:
                calls.append(
                    (
                        tuple(crop.shape),
                        include_interaction,
                        run_prediction,
                        interaction_bbox,
                    )
                )

        prompt = np.zeros((2, 4, 4), dtype=bool)
        prompt[0, 1, 1] = True
        prompt[1, 2, 2] = True

        accepted = BRIDGE._apply_interaction(Session(), prompt, "scribble", True)

        self.assertTrue(accepted)
        self.assertEqual(2, len(calls))
        self.assertFalse(calls[0][2])
        self.assertTrue(calls[1][2])

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

            def __init__(self) -> None:
                self.point_calls = []

            def set_image(self, image: np.ndarray) -> None:
                self.image = image

            def set_target_buffer(self, target: np.ndarray) -> None:
                self.target = target

            def reset_interactions(self) -> None:
                self.target.fill(0)

            def add_initial_seg_interaction(
                self, initial: np.ndarray, run_prediction: bool = False
            ) -> None:
                self.target[:] = initial

            def add_point_interaction(
                self,
                point: tuple[int, int, int],
                include_interaction: bool,
                run_prediction: bool = True,
            ) -> None:
                self.point_calls.append((point, include_interaction, run_prediction))
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

            session = FakeSession()
            with (
                patch.object(
                    BRIDGE,
                    "_ensure_server",
                    return_value=(False, "http://127.0.0.1:1527", "test-api-key"),
                ),
                patch.object(BRIDGE, "_connect_remote", return_value=session),
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
                                "interaction_type": "point_set",
                                "coordinates": "mimics",
                                "points": [
                                    {
                                        "point": [2, 2, 0],
                                        "include_interaction": True,
                                    },
                                    {
                                        "point": [0, 0, 0],
                                        "include_interaction": False,
                                    },
                                ],
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
            self.assertEqual(1, result["interaction_count"])
            self.assertEqual("test-license", result["model_license"])
            self.assertEqual(0, int(output[0, 0, 0]))
            self.assertEqual(1, int(output[2, 2, 0]))
            self.assertEqual(
                [
                    ((2, 2, 0), True, False),
                    ((0, 0, 0), False, True),
                ],
                session.point_calls,
            )

    def test_persistent_context_preprocesses_image_only_once(self) -> None:
        class FakeSession:
            license = "test-license"

            def __init__(self) -> None:
                self.set_image_calls = 0
                self.reset_calls = 0

            def set_image(self, image: np.ndarray) -> None:
                self.set_image_calls += 1
                self.image = image

            def set_target_buffer(self, target: np.ndarray) -> None:
                self.target = target

            def reset_interactions(self) -> None:
                self.reset_calls += 1
                self.target.fill(0)

            def add_point_interaction(
                self,
                point: tuple[int, int, int],
                include_interaction: bool,
                run_prediction: bool = True,
            ) -> None:
                self.target[point] = 1 if include_interaction else 0

            def close(self) -> None:
                return None

        with TemporaryDirectory() as directory:
            root = Path(directory)
            shape = [4, 4, 1]
            image_path = root / "image.raw"
            np.zeros(shape, dtype=np.int16).tofile(image_path)
            request = {
                "image_buffer_path": str(image_path),
                "image_buffer_shape": shape,
                "image_buffer_dtype": "int16",
                "image_buffer_coordinates": "mimics",
                "buffer_mapping": {
                    "platform_to_mimics_axes": [0, 1, 2],
                    "platform_to_mimics_flips": [False, False, False],
                },
                "model_dir": str(root),
                "device": "cpu",
            }
            session = FakeSession()
            with (
                patch.object(
                    BRIDGE,
                    "_ensure_server",
                    return_value=(False, "http://127.0.0.1:1527", "test-api-key"),
                ),
                patch.object(BRIDGE, "_connect_remote", return_value=session),
            ):
                context = BRIDGE._BridgeSessionContext(request)
                try:
                    for index in range(2):
                        context.predict(
                            [
                                {
                                    "interaction_type": "point_set",
                                    "coordinates": "mimics",
                                    "points": [
                                        {
                                            "point": [index + 1, index + 1, 0],
                                            "include_interaction": True,
                                        }
                                    ],
                                }
                            ],
                            str(root / f"result_{index}.u8"),
                        )
                finally:
                    context.close()

        self.assertEqual(1, session.set_image_calls)
        self.assertEqual(2, session.reset_calls)

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
        self.assertIn('set "DEVICE=auto"', content)
        self.assertNotIn("--fold all", content)
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
