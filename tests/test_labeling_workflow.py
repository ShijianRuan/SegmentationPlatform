from __future__ import annotations

import json
import importlib.util
import py_compile
import sys
import tempfile
import types
import unittest
from pathlib import Path

import numpy as np
import pydicom
import yaml
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from segplatform.adapters.mimics.finalize import finalize_case
from segplatform.adapters.mimics.bridge import read_export_buffer
from segplatform.adapters.mimics.launcher import open_case
from segplatform.adapters.mimics.prepare import prepare_case
from segplatform.adapters.mimics.probes import build_probe_command, evaluate_probe, solve_buffer_mapping
from segplatform.case_packages import create_case_package
from segplatform.common import load_data
from segplatform.imaging import inspect_dicom_series, write_mask_nifti
from segplatform.imaging import BufferMapping
from segplatform.ingest import build_case_package_requests, scan_source
from segplatform.errors import ValidationError
from segplatform.registry import FileRegistry
from segplatform.snapshots import create_snapshot, validate_snapshot


class LabelingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def make_dicom_series(self) -> Path:
        series_root = self.root / "dicom"
        series_root.mkdir()
        study_uid = generate_uid()
        series_uid = generate_uid()
        for index in range(3):
            meta = FileMetaDataset()
            meta.TransferSyntaxUID = ExplicitVRLittleEndian
            meta.MediaStorageSOPClassUID = CTImageStorage
            meta.MediaStorageSOPInstanceUID = generate_uid()
            dataset = FileDataset(
                str(series_root / f"slice_{index:03d}.dcm"),
                {},
                file_meta=meta,
                preamble=b"\0" * 128,
            )
            dataset.SOPClassUID = CTImageStorage
            dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
            dataset.PatientName = "ANON"
            dataset.PatientID = "PSEUDO_001"
            dataset.StudyInstanceUID = study_uid
            dataset.SeriesInstanceUID = series_uid
            dataset.SeriesDescription = "VENOUS"
            dataset.Modality = "CT"
            dataset.Rows = 5
            dataset.Columns = 6
            dataset.PixelSpacing = [1.5, 1.0]
            dataset.SliceThickness = 2.0
            dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            dataset.ImagePositionPatient = [0, 0, index * 2.0]
            dataset.InstanceNumber = index + 1
            dataset.SamplesPerPixel = 1
            dataset.PhotometricInterpretation = "MONOCHROME2"
            dataset.BitsAllocated = 16
            dataset.BitsStored = 16
            dataset.HighBit = 15
            dataset.PixelRepresentation = 1
            dataset.PixelData = np.zeros((5, 6), dtype=np.int16).tobytes()
            dataset.save_as(series_root / f"slice_{index:03d}.dcm", enforce_file_format=True)
        return series_root

    def make_request(self, dicom_root: Path, mask_path: Path) -> Path:
        request = {
            "schema_version": "case_package_request.v1",
            "package_id": "pkg_case_001",
            "case_id": "case_001",
            "study_id": "study_001",
            "leakage_group_id": "patient_001",
            "leakage_group_basis": "patient_pseudonym",
            "leakage_group_confidence": "high",
            "data_governance": {
                "source_zone": "working",
                "deidentification_status": "verified",
                "profile": "test",
                "profile_version": "1",
                "direct_identifiers_allowed": False,
            },
            "image_sets": [
                {
                    "image_id": "img_venous",
                    "modality": "CT",
                    "format": "dicom_series",
                    "source": str(dicom_root),
                    "import_batch": "test",
                }
            ],
            "review": {
                "review_id": "review_case_001_v1",
                "tool": "mimics",
                "assignee": "annotator_01",
                "targets": [
                    {
                        "target_id": "target_liver",
                        "image_id": "img_venous",
                        "organs": ["liver"],
                    }
                ],
            },
            "initial_labels": [
                {
                    "image_id": "img_venous",
                    "organ": "liver",
                    "path": str(mask_path),
                    "lifecycle_status": "candidate_label",
                    "generator_id": "test_generator",
                }
            ],
        }
        path = self.root / "package_request.yaml"
        path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
        return path

    def workstation_config(self, verified: bool = True) -> Path:
        executable = self.root / "MimicsResearch.exe"
        executable.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
        executable.chmod(0o755)
        config = {
            "schema_version": "mimics_workstation.v1",
            "expected_product": "Mimics Research",
            "expected_version": "21.0",
            "executable": str(executable),
            "runtime_script_dir": str(Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"),
            "probe_script_dir": str(Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "probes"),
            "work_root": str(self.root / "work"),
            "buffer_mapping": {
                "schema_version": "mimics_buffer_mapping.v1",
                "status": "verified" if verified else "unverified",
                "evidence_id": "p05_test" if verified else "",
                "platform_to_mimics_axes": [0, 1, 2],
                "platform_to_mimics_flips": [False, False, False],
            },
        }
        path = self.root / ("mimics_verified.yaml" if verified else "mimics_unverified.yaml")
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return path

    def test_end_to_end_before_training(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        mask[1:4, 1:4, 1] = 1
        source_mask = self.root / "liver.nii.gz"
        write_mask_nifti(source_mask, mask, geometry)

        registry_root = self.root / "registry"
        case_root = create_case_package(
            self.make_request(dicom_root, source_mask),
            self.root / "dataset_package",
            registry_root=registry_root,
        )
        self.assertTrue((registry_root / "_indexes" / "labels_by_case_image_organ.json").is_file())
        runtime_path = prepare_case(case_root, self.workstation_config(verified=True))
        runtime = load_data(runtime_path)
        self.assertEqual("new", runtime["mode"])
        self.assertEqual(1, len(runtime["import_buffers"]))
        base_target = runtime["targets"][0]
        self.assertTrue(base_target["base_label_id"])
        launch = open_case(
            case_root,
            self.workstation_config(verified=True),
            wait=True,
            registry_root=registry_root,
        )
        self.assertEqual(0, launch["returncode"])
        self.assertEqual("in_progress", FileRegistry(registry_root).get("reviews", runtime["review_id"])["status"])

        submission_root = case_root / "submissions" / runtime["review_id"]
        output_buffer = submission_root / "buffers" / "img_venous" / "target_liver" / "liver.u8"
        output_buffer.parent.mkdir(parents=True)
        output_buffer.write_bytes(mask.tobytes(order="C"))
        from segplatform.common import prefixed_sha256

        (submission_root / "export_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "mimics_export_manifest.v1",
                    "review_id": runtime["review_id"],
                    "mimics_version": "21.0",
                    "python_version": "3.5.2",
                    "entries": [
                        {
                            "target_id": "target_liver",
                            "image_id": "img_venous",
                            "organ": "liver",
                            "path": output_buffer.relative_to(case_root).as_posix(),
                            "path_base": "package_root",
                            "sha256": prefixed_sha256(output_buffer),
                            "byte_count": output_buffer.stat().st_size,
                            "mimics_shape": list(mask.shape),
                            "platform_shape": list(mask.shape),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (submission_root / "submission_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "review_submission.v1",
                    "review_id": runtime["review_id"],
                    "target_ids": ["target_liver"],
                    "action": "submit_complete",
                    "assignee": "annotator_01",
                    "base_labels": {
                        "target_liver": {
                            "label_id": base_target["base_label_id"],
                            "sha256": base_target["base_label_sha256"],
                        }
                    },
                    "organ_outcomes": {"target_liver": {"liver": "present"}},
                }
            ),
            encoding="utf-8",
        )
        result = finalize_case(case_root, self.workstation_config(verified=True), registry_root)
        self.assertEqual("passed", result["status"])
        self.assertEqual(1, len(result["label_ids"]))
        review = FileRegistry(registry_root).get("reviews", runtime["review_id"])
        self.assertEqual("completed", review["status"])

        snapshot_request = {
            "schema_version": "snapshot_request.v1",
            "snapshot_id": "snapshot_001",
            "task_id": "liver_task",
            "task_label_map": {"background": 0, "liver": 1},
            "label_policy": {"allow_lifecycle_status": ["verified_label"]},
            "cases": [
                {
                    "case_id": "case_001",
                    "image_id": "img_venous",
                    "split": "train",
                    "segments": [{"organ": "liver", "label_id": result["label_ids"][0]}],
                }
            ],
            "preprocess_profile": {"name": "none"},
            "usage_constraints": {
                "model_training": "allowed",
                "commercial_use": "needs_policy",
                "redistribution": "forbidden",
            },
        }
        snapshot_request_path = self.root / "snapshot.yaml"
        snapshot_request_path.write_text(yaml.safe_dump(snapshot_request, sort_keys=False), encoding="utf-8")
        snapshot = create_snapshot(snapshot_request_path, registry_root)
        self.assertEqual("snapshot_001", snapshot["snapshot_id"])
        validate_snapshot(registry_root / "snapshots" / "snapshot_001.json")

    def test_unverified_mapping_blocks_initial_mask_bridge(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        source_mask = self.root / "liver.nii.gz"
        write_mask_nifti(source_mask, np.zeros(geometry.shape, dtype=np.uint8), geometry)
        case_root = create_case_package(self.make_request(dicom_root, source_mask), self.root / "dataset_package")
        with self.assertRaisesRegex(Exception, "not verified"):
            prepare_case(case_root, self.workstation_config(verified=False))

    def test_ingest_scan_builds_requests_without_manual_image_sets(self) -> None:
        dicom_root = self.make_dicom_series()
        scan = scan_source(dicom_root)
        self.assertEqual(1, scan["summary"]["importable_series_count"])
        encoded = json.dumps(scan)
        self.assertNotIn("PSEUDO_001", encoded)

        scan_path = self.root / "scan.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        requests_dir = self.root / "requests"
        batch = build_case_package_requests(
            scan_path,
            requests_dir,
            organs=["liver"],
            import_batch="batch_test",
            assignee="annotator_01",
        )
        self.assertEqual(1, batch["request_count"])
        request_path = Path(batch["requests"][0])
        request = load_data(request_path)
        self.assertEqual("dicom_series", request["image_sets"][0]["format"])
        self.assertTrue(request["image_sets"][0]["source_files"])

        case_root = create_case_package(request_path, self.root / "dataset_package")
        manifest = load_data(case_root / "manifest.json")
        self.assertEqual(1, len(manifest["image_sets"]))
        self.assertEqual(["liver"], manifest["review"]["targets"][0]["organs"])

    def test_windows_probe_command_and_mapping_evaluation(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, details = inspect_dicom_series(dicom_root)
        source_mask = self.root / "liver.nii.gz"
        write_mask_nifti(source_mask, np.zeros(geometry.shape, dtype=np.uint8), geometry)
        case_root = create_case_package(self.make_request(dicom_root, source_mask), self.root / "dataset_package")
        config_path = self.workstation_config(verified=False)

        command, output_dir = build_probe_command(case_root, config_path)
        self.assertEqual(str(case_root / "reports" / "mimics_probe"), str(output_dir))
        self.assertIn("sp_probe_suite.py", command[4])

        def world(index: tuple[int, int, int]) -> list[float]:
            direction = np.asarray(geometry.direction).reshape(3, 3)
            value = np.asarray(geometry.origin) + direction @ (
                np.asarray(geometry.spacing) * np.asarray(index, dtype=float)
            )
            return [float(item) for item in value]

        indexes = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (5, 4, 2)]
        evidence = {
            "schema_version": "mimics_probe_suite.v1",
            "status": "passed",
            "sections": {
                "p01": {
                    "status": "passed",
                    "image_sets": [
                        {
                            "logical_dimensions": list(geometry.shape),
                            "dicom_series_uid_sha256": details["dicom_series_uid_sha256"],
                        }
                    ],
                },
                "p02": {"status": "passed"},
                "p04": {"status": "passed"},
                "p05": {
                    "status": "evidence_collected",
                    "logical_dimensions": list(geometry.shape),
                    "voxel_centers": [{"index": list(index), "world": world(index)} for index in indexes],
                },
                "p06": {"status": "passed"},
            },
        }
        evidence_path = self.root / "mimics_probe_evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        from segplatform.common import prefixed_sha256

        (self.root / "mimics_probe_complete.json").write_text(
            json.dumps(
                {
                    "schema_version": "mimics_probe_complete.v1",
                    "status": "passed",
                    "evidence_path": str(evidence_path),
                    "evidence_sha256": prefixed_sha256(evidence_path),
                }
            ),
            encoding="utf-8",
        )
        generated_config = self.root / "mimics_workstation.verified.yaml"
        report = evaluate_probe(case_root, evidence_path, config_path, generated_config)

        self.assertEqual("passed", report["status"])
        generated = load_data(generated_config)
        self.assertEqual("verified", generated["buffer_mapping"]["status"])
        self.assertEqual([0, 1, 2], generated["buffer_mapping"]["platform_to_mimics_axes"])
        self.assertEqual([False, False, False], generated["buffer_mapping"]["platform_to_mimics_flips"])

    def test_relative_export_buffer_cannot_escape_case_package(self) -> None:
        case_root = self.root / "case"
        case_root.mkdir()
        outside = self.root / "outside.u8"
        outside.write_bytes(b"\0")
        mapping = BufferMapping(
            axes=(0, 1, 2),
            flips=(False, False, False),
            status="verified",
            evidence_id="test",
        )
        entry = {
            "path": "../outside.u8",
            "path_base": "package_root",
            "sha256": "sha256:unused",
            "mimics_shape": [1, 1, 1],
            "platform_shape": [1, 1, 1],
        }
        with self.assertRaisesRegex(ValidationError, "escapes Case Package"):
            read_export_buffer(entry, mapping, case_root=case_root)

    def test_probe_mapping_solver_handles_axis_permutation_and_flips(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        image_manifest = geometry.as_manifest()
        axes = (2, 0, 1)
        flips = (True, False, True)
        mimics_shape = tuple(geometry.shape[axis] for axis in axes)

        def observed_world(mimics_index: tuple[int, int, int]) -> list[float]:
            transposed = np.asarray(mimics_index, dtype=float)
            for axis, should_flip in enumerate(flips):
                if should_flip:
                    transposed[axis] = mimics_shape[axis] - 1 - transposed[axis]
            platform_index = np.zeros(3, dtype=float)
            for mimics_axis, platform_axis in enumerate(axes):
                platform_index[platform_axis] = transposed[mimics_axis]
            direction = np.asarray(geometry.direction).reshape(3, 3)
            value = np.asarray(geometry.origin) + direction @ (
                np.asarray(geometry.spacing) * platform_index
            )
            return [float(item) for item in value]

        indexes = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), tuple(value - 1 for value in mimics_shape)]
        result = solve_buffer_mapping(
            image_manifest,
            {
                "logical_dimensions": list(mimics_shape),
                "voxel_centers": [
                    {"index": list(index), "world": observed_world(index)}
                    for index in indexes
                ],
            },
        )
        self.assertEqual("passed", result["status"])
        self.assertEqual(list(axes), result["best"]["axes"])
        self.assertEqual(list(flips), result["best"]["flips"])

    def test_submit_dialog_supports_target_combinations_and_bulk_empty_outcomes(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"
        responses = iter(["[ ] 1", "[ ] 3", "Use Selected", "All Confirmed Absent"])

        class Dialogs:
            @staticmethod
            def question_box(**_kwargs):
                return next(responses)

            @staticmethod
            def message_box(*_args, **_kwargs):
                return None

        fake_mimics = types.SimpleNamespace(dialogs=Dialogs())
        previous_mimics = sys.modules.get("mimics")
        sys.modules["mimics"] = fake_mimics
        sys.path.insert(0, str(runtime_dir))
        self.addCleanup(lambda: sys.path.remove(str(runtime_dir)))

        def restore_mimics() -> None:
            if previous_mimics is None:
                sys.modules.pop("mimics", None)
            else:
                sys.modules["mimics"] = previous_mimics

        self.addCleanup(restore_mimics)
        spec = importlib.util.spec_from_file_location("sp_submit_review_test", runtime_dir / "sp_submit_review.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        selected = module.choose_targets(
            {"targets": [{"target_id": "target_a"}, {"target_id": "target_b"}, {"target_id": "target_c"}]}
        )
        self.assertEqual(["target_a", "target_c"], selected)
        outcomes, needs_review = module.resolve_empty_masks(
            [("target_a", "liver"), ("target_c", "kidney_left")]
        )
        self.assertFalse(needs_review)
        self.assertEqual("confirmed_absent", outcomes[("target_a", "liver")])
        self.assertEqual("confirmed_absent", outcomes[("target_c", "kidney_left")])

        import sp_common

        class Tag:
            def __init__(self, value):
                self.value = value

        class Image:
            def __init__(self, uid, shape):
                self.logical_dimensions = shape
                self._tags = {(0x0020, 0x000E): Tag(uid), (0x0008, 0x103E): Tag("VENOUS")}

            def get_dicom_tags(self):
                return self._tags

        uid = "1.2.3.4"
        wrong_shape_image = Image(uid, [10, 10, 10])
        image_container = types.SimpleNamespace(data=types.SimpleNamespace(images=[wrong_shape_image]))
        expected = {
            "image_id": "img",
            "dicom_series_uid_sha256": sp_common.sha256_bytes(uid.encode("utf-8")),
            "platform_shape": [6, 5, 3],
            "series_description": "VENOUS",
        }
        with self.assertRaisesRegex(RuntimeError, "shape differs"):
            sp_common.match_images(image_container, [expected])

        checkpoint_array = np.zeros((3, 4, 5), dtype=np.bool_)
        checkpoint_array[1, 2, 3] = True

        class BufferMask:
            def __init__(self, array=None):
                self.array = array
                self.number_of_pixels = int(array.sum()) if array is not None else 0

            def get_voxel_buffer(self):
                return self.array

            def set_voxel_buffer(self, value):
                self.array = np.asarray(value)
                self.number_of_pixels = int(self.array.sum())

        checkpoint_path = self.root / "checkpoint.u8.gz"
        exported = sp_common.export_mask_u8_gzip(BufferMask(checkpoint_array), str(checkpoint_path))
        restored = BufferMask()
        method = sp_common.set_mask_buffer_from_u8(restored, str(checkpoint_path), checkpoint_array.shape)
        self.assertEqual("gzip", exported["compression"])
        self.assertIn(method, {"numpy", "memoryview"})
        np.testing.assert_array_equal(checkpoint_array, restored.array)

    def test_resume_rejects_stale_base_label_metadata(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"
        previous_mimics = sys.modules.get("mimics")
        sys.modules["mimics"] = types.SimpleNamespace()
        sys.path.insert(0, str(runtime_dir))
        self.addCleanup(lambda: sys.path.remove(str(runtime_dir)))

        def restore_mimics() -> None:
            if previous_mimics is None:
                sys.modules.pop("mimics", None)
            else:
                sys.modules["mimics"] = previous_mimics

        self.addCleanup(restore_mimics)
        spec = importlib.util.spec_from_file_location("sp_open_review_test", runtime_dir / "sp_open_review.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        class Metadata:
            def __init__(self, values):
                self.values = values

            def find(self, name):
                value = self.values.get(name)
                return None if value is None else types.SimpleNamespace(value=value)

        mask = types.SimpleNamespace(
            metadata=Metadata(
                {
                    "sp.image_id": "img_venous",
                    "sp.base_label_id": "label_old",
                    "sp.base_label_hash": "sha256:old",
                }
            )
        )
        target = {
            "target_id": "target_liver",
            "image_id": "img_venous",
            "base_label_id": "label_new",
            "base_label_sha256": "sha256:new",
        }
        with self.assertRaisesRegex(RuntimeError, "different task version"):
            module.validate_existing_mask(mask, target, "liver", {"package_root": str(self.root)})

    def test_checkpoint_is_loaded_and_rebuild_preserves_old_mcs(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        source_mask = self.root / "liver.nii.gz"
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        mask[1, 1, 1] = 1
        write_mask_nifti(source_mask, mask, geometry)
        case_root = create_case_package(self.make_request(dicom_root, source_mask), self.root / "dataset_package")
        config_path = self.workstation_config(verified=True)
        runtime = load_data(prepare_case(case_root, config_path))
        target = runtime["targets"][0]

        checkpoint_root = (
            case_root / "working" / "checkpoints" / runtime["review_id"] / "20260615T000000Z"
        )
        buffer_path = checkpoint_root / "buffers" / "img_venous" / "target_liver" / "liver.u8"
        buffer_path.parent.mkdir(parents=True)
        buffer_path.write_bytes(mask.tobytes(order="C"))
        from segplatform.common import prefixed_sha256

        checkpoint_manifest = checkpoint_root / "checkpoint_manifest.json"
        checkpoint_manifest.write_text(
            json.dumps(
                {
                    "schema_version": "mimics_checkpoint.v1",
                    "review_id": runtime["review_id"],
                    "package_id": runtime["package_id"],
                    "buffer_mapping_evidence_id": "p05_test",
                    "base_labels": {
                        "target_liver": {
                            "label_id": target["base_label_id"],
                            "sha256": target["base_label_sha256"],
                        }
                    },
                    "entries": [
                        {
                            "target_id": "target_liver",
                            "image_id": "img_venous",
                            "organ": "liver",
                            "path": buffer_path.relative_to(case_root).as_posix(),
                            "path_base": "package_root",
                            "sha256": prefixed_sha256(buffer_path),
                            "byte_count": buffer_path.stat().st_size,
                            "mimics_shape": list(mask.shape),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        latest = checkpoint_root.parent / "latest.json"
        latest.write_text(
            json.dumps(
                {
                    "schema_version": "mimics_checkpoint_pointer.v1",
                    "review_id": runtime["review_id"],
                    "checkpoint_manifest": checkpoint_manifest.relative_to(case_root).as_posix(),
                }
            ),
            encoding="utf-8",
        )
        prepared = load_data(prepare_case(case_root, config_path))
        self.assertEqual(1, len(prepared["checkpoint_buffers"]))

        mcs_path = Path(prepared["mcs_path"])
        mcs_path.write_bytes(b"damaged")
        rebuilt = load_data(prepare_case(case_root, config_path, rebuild_workspace=True))
        self.assertEqual("new", rebuilt["mode"])
        self.assertFalse(mcs_path.exists())
        self.assertEqual(1, len(list(mcs_path.parent.glob(mcs_path.name + ".backup.*"))))

    def test_sheared_dicom_grid_is_rejected(self) -> None:
        dicom_root = self.make_dicom_series()
        for index, path in enumerate(sorted(dicom_root.glob("*.dcm"))):
            dataset = pydicom.dcmread(path)
            dataset.ImagePositionPatient = [index * 0.2, 0, index * 2.0]
            dataset.save_as(path, enforce_file_format=True)
        with self.assertRaisesRegex(ValidationError, "sheared or tilted"):
            inspect_dicom_series(dicom_root)

    def test_mimics_scripts_compile_with_conservative_syntax(self) -> None:
        root = Path(__file__).resolve().parents[1] / "adapters" / "mimics"
        for path in sorted(root.rglob("*.py")):
            py_compile.compile(str(path), doraise=True)


if __name__ == "__main__":
    unittest.main()
