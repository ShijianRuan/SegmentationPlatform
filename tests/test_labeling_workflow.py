from __future__ import annotations

import json
import importlib.util
import os
import py_compile
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import nibabel as nib
import pydicom
import yaml
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from segplatform.adapters.mimics.finalize import finalize_case
from segplatform.adapters.mimics.bridge import read_export_buffer
from segplatform.adapters.mimics.launcher import open_case, prebuild_workspace
from segplatform.adapters.mimics.prepare import prepare_case
from segplatform.adapters.mimics.probes import build_probe_command, evaluate_probe, solve_buffer_mapping
from segplatform.case_packages import create_case_package
from segplatform.common import load_data, write_json
from segplatform.dataset_descriptions import build_requests_from_dataset_description
from segplatform.distribution import collect_submissions, export_worklist
from segplatform.imaging import geometry_matches, inspect_dicom_series, inspect_image, read_mask, write_mask_nifti
from segplatform.imaging import BufferMapping
from segplatform.ingest import build_case_package_requests, register_scan, scan_source
from segplatform.labels import merge_labels, register_label, register_labels_from_table
from segplatform.errors import ValidationError
from segplatform.registry import FileRegistry
from segplatform.review_updates import create_followup_reviews, create_followup_reviews_from_findings
from segplatform.reviews import assign_review, defer_review, next_review, reactivate_review
from segplatform.snapshots import build_snapshot_request, create_snapshot, validate_snapshot


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

        prebuild = prebuild_workspace(case_root, self.workstation_config(verified=True), dry_run=True)
        self.assertFalse(prebuild["started"])
        self.assertIn("-background_mode", prebuild["command"])
        self.assertIn("--background-prebuild", prebuild["command"])
        self.assertTrue(prebuild["command"][-2].endswith("mimics_runtime.json"))

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
        self.assertEqual("training", snapshot["cases"][0]["image_usability"]["purpose"])
        validate_snapshot(registry_root / "snapshots" / "snapshot_001.json")

    def test_per_image_buffer_mapping_override_for_prepare_and_finalize(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        liver_mask = np.zeros(geometry.shape, dtype=np.uint8)
        liver_mask[1:4, 1:4, 1] = 1
        spleen_mask = np.zeros(geometry.shape, dtype=np.uint8)
        spleen_mask[0:2, 0:2, 1] = 1
        liver_path = self.root / "override_liver.nii.gz"
        spleen_path = self.root / "override_spleen.nii.gz"
        write_mask_nifti(liver_path, liver_mask, geometry)
        write_mask_nifti(spleen_path, spleen_mask, geometry)

        request = {
            "schema_version": "case_package_request.v1",
            "package_id": "pkg_case_override",
            "case_id": "case_override",
            "study_id": "study_override",
            "leakage_group_id": "patient_override",
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
                    "image_id": "img_default",
                    "modality": "CT",
                    "format": "dicom_series",
                    "source": str(dicom_root),
                    "import_batch": "test",
                },
                {
                    "image_id": "img_swapped",
                    "modality": "CT",
                    "format": "dicom_series",
                    "source": str(dicom_root),
                    "import_batch": "test",
                },
            ],
            "review": {
                "review_id": "review_case_override_v1",
                "tool": "mimics",
                "assignee": "annotator_01",
                "targets": [
                    {"target_id": "target_default", "image_id": "img_default", "organs": ["liver"]},
                    {"target_id": "target_swapped", "image_id": "img_swapped", "organs": ["spleen"]},
                ],
            },
            "initial_labels": [
                {
                    "image_id": "img_default",
                    "organ": "liver",
                    "path": str(liver_path),
                    "lifecycle_status": "source_label",
                },
                {
                    "image_id": "img_swapped",
                    "organ": "spleen",
                    "path": str(spleen_path),
                    "lifecycle_status": "source_label",
                },
            ],
        }
        request_path = self.root / "package_request_override.yaml"
        request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
        registry_root = self.root / "registry_override"
        case_root = create_case_package(request_path, self.root / "dataset_package_override", registry_root=registry_root)

        config_path = self.workstation_config(verified=True)
        config = load_data(config_path)
        config["buffer_mapping"]["evidence_id"] = "p05_default"
        config["buffer_mapping_by_image_id"] = {
            "img_swapped": {
                "schema_version": "mimics_buffer_mapping.v1",
                "status": "verified",
                "evidence_id": "p05_swapped",
                "platform_to_mimics_axes": [2, 1, 0],
                "platform_to_mimics_flips": [False, False, False],
            }
        }
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        runtime = load_data(prepare_case(case_root, config_path))
        imports = {(entry["image_id"], entry["organ"]): entry for entry in runtime["import_buffers"]}
        self.assertEqual(list(geometry.shape), imports[("img_default", "liver")]["mimics_shape"])
        self.assertEqual(
            [geometry.shape[2], geometry.shape[1], geometry.shape[0]],
            imports[("img_swapped", "spleen")]["mimics_shape"],
        )
        self.assertEqual("p05_swapped", imports[("img_swapped", "spleen")]["buffer_mapping_evidence_id"])

        submission_root = case_root / "submissions" / runtime["review_id"]
        default_buffer = submission_root / "buffers" / "img_default" / "target_default" / "liver.u8"
        swapped_buffer = submission_root / "buffers" / "img_swapped" / "target_swapped" / "spleen.u8"
        default_buffer.parent.mkdir(parents=True)
        swapped_buffer.parent.mkdir(parents=True)
        default_buffer.write_bytes(liver_mask.tobytes(order="C"))
        swapped_array = BufferMapping(
            axes=(2, 1, 0),
            flips=(False, False, False),
            status="verified",
            evidence_id="p05_swapped",
        ).platform_to_mimics(spleen_mask)
        swapped_buffer.write_bytes(swapped_array.tobytes(order="C"))
        from segplatform.common import prefixed_sha256

        target_by_id = {target["target_id"]: target for target in runtime["targets"]}
        (submission_root / "export_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "mimics_export_manifest.v1",
                    "review_id": runtime["review_id"],
                    "mimics_version": "21.0",
                    "python_version": "3.5.2",
                    "entries": [
                        {
                            "target_id": "target_default",
                            "image_id": "img_default",
                            "organ": "liver",
                            "path": default_buffer.relative_to(case_root).as_posix(),
                            "path_base": "package_root",
                            "sha256": prefixed_sha256(default_buffer),
                            "byte_count": default_buffer.stat().st_size,
                            "mimics_shape": list(liver_mask.shape),
                            "platform_shape": list(liver_mask.shape),
                        },
                        {
                            "target_id": "target_swapped",
                            "image_id": "img_swapped",
                            "organ": "spleen",
                            "path": swapped_buffer.relative_to(case_root).as_posix(),
                            "path_base": "package_root",
                            "sha256": prefixed_sha256(swapped_buffer),
                            "byte_count": swapped_buffer.stat().st_size,
                            "mimics_shape": list(swapped_array.shape),
                            "platform_shape": list(spleen_mask.shape),
                        },
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
                    "target_ids": ["target_default", "target_swapped"],
                    "action": "submit_complete",
                    "assignee": "annotator_01",
                    "base_labels": {
                        target_id: {
                            "label_id": target.get("base_label_id", ""),
                            "sha256": target.get("base_label_sha256", ""),
                        }
                        for target_id, target in target_by_id.items()
                    },
                    "organ_outcomes": {
                        "target_default": {"liver": "present"},
                        "target_swapped": {"spleen": "present"},
                    },
                }
            ),
            encoding="utf-8",
        )

        result = finalize_case(case_root, config_path, registry_root)
        records_by_image = {record["image_id"]: record for record in result["records"]}
        restored_spleen, _ = read_mask(Path(records_by_image["img_swapped"]["segments"][0]["path"]))
        self.assertTrue(np.array_equal(restored_spleen != 0, spleen_mask != 0))
        tool_export = load_data(case_root / "provenance" / "tool_export.json")
        self.assertEqual("p05_swapped", tool_export["buffer_mapping_evidence_by_image_id"]["img_swapped"])

    def test_snapshot_respects_image_usability(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        source_mask = self.root / "liver_snapshot_usability.nii.gz"
        write_mask_nifti(source_mask, np.zeros(geometry.shape, dtype=np.uint8), geometry)

        registry_root = self.root / "registry_snapshot_usability"
        create_case_package(
            self.make_request(dicom_root, source_mask),
            self.root / "usability_package",
            registry_root=registry_root,
        )
        registry = FileRegistry(registry_root)
        label_id = registry.find_labels(case_id="case_001", image_id="img_venous", organ="liver")[0]["label_id"]
        image_path = registry_root / "images" / "img_venous.json"
        image_record = load_data(image_path)

        snapshot_request = {
            "schema_version": "snapshot_request.v1",
            "snapshot_id": "snapshot_usability",
            "task_id": "liver_task",
            "task_label_map": {"background": 0, "liver": 1},
            "label_policy": {"allow_lifecycle_status": ["candidate_label"]},
            "cases": [
                {
                    "case_id": "case_001",
                    "image_id": "img_venous",
                    "split": "train",
                    "segments": [{"organ": "liver", "label_id": label_id}],
                }
            ],
            "preprocess_profile": {"name": "none"},
            "usage_constraints": {
                "model_training": "allowed",
                "commercial_use": "needs_policy",
                "redistribution": "needs_policy",
            },
        }
        snapshot_request_path = self.root / "snapshot_usability.yaml"
        snapshot_request_path.write_text(yaml.safe_dump(snapshot_request, sort_keys=False), encoding="utf-8")

        image_record["usability"]["training"] = "blocked"
        image_record["usability"]["reasons"] = ["training forbidden by source image QC"]
        write_json(image_path, image_record)
        with self.assertRaisesRegex(ValidationError, r"usability\.training is blocked"):
            create_snapshot(snapshot_request_path, registry_root)
        report = build_snapshot_request(
            registry_root,
            self.root / "snapshot_usability_request.yaml",
            snapshot_id="snapshot_usability_request",
            task_id="liver_task",
            organs=["liver"],
            allow_lifecycle_status=["candidate_label"],
        )
        self.assertEqual(0, report["case_image_count"])
        self.assertEqual("image_usability_blocked", report["skipped"][0]["reason"])
        self.assertEqual("training", report["skipped"][0]["usability_purpose"])

        image_record["usability"]["training"] = "allowed"
        image_record["usability"]["evaluation"] = "blocked"
        image_record["usability"]["reasons"] = ["patient linkage is too weak for evaluation"]
        write_json(image_path, image_record)
        snapshot_request["snapshot_id"] = "snapshot_eval_usability"
        snapshot_request["cases"][0]["split"] = "val"
        snapshot_request_path.write_text(yaml.safe_dump(snapshot_request, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, r"usability\.evaluation is blocked"):
            create_snapshot(snapshot_request_path, registry_root)
        report = build_snapshot_request(
            registry_root,
            self.root / "snapshot_eval_usability_request.yaml",
            snapshot_id="snapshot_eval_usability_request",
            task_id="liver_task",
            organs=["liver"],
            default_split="test",
            allow_lifecycle_status=["candidate_label"],
        )
        self.assertEqual(0, report["case_image_count"])
        self.assertEqual("evaluation", report["skipped"][0]["usability_purpose"])

    def test_known_absent_organ_skipped_across_prepare_and_finalize(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        liver_mask = np.zeros(geometry.shape, dtype=np.uint8)
        liver_mask[1:4, 1:4, 1] = 1

        request = {
            "schema_version": "case_package_request.v1",
            "package_id": "pkg_case_002",
            "case_id": "case_002",
            "study_id": "study_002",
            "leakage_group_id": "patient_002",
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
                "review_id": "review_case_002_v1",
                "tool": "mimics",
                "assignee": "annotator_01",
                "targets": [
                    {
                        "target_id": "target_abdomen",
                        "image_id": "img_venous",
                        "organs": ["liver", "spleen"],
                        "known_absent": ["spleen"],
                    }
                ],
            },
            "initial_labels": [],
        }
        request_path = self.root / "package_request_known_absent.yaml"
        request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")

        registry_root = self.root / "registry_known_absent"
        case_root = create_case_package(
            request_path,
            self.root / "dataset_package_known_absent",
            registry_root=registry_root,
        )
        manifest = load_data(case_root / "manifest.json")
        self.assertEqual(["spleen"], manifest["review"]["targets"][0]["known_absent"])

        runtime = load_data(prepare_case(case_root, self.workstation_config(verified=True)))
        self.assertEqual(["liver"], [mask["organ"] for mask in runtime["targets"][0]["masks"]])

        submission_root = case_root / "submissions" / runtime["review_id"]
        output_buffer = submission_root / "buffers" / "img_venous" / "target_abdomen" / "liver.u8"
        output_buffer.parent.mkdir(parents=True)
        output_buffer.write_bytes(liver_mask.tobytes(order="C"))
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
                            "target_id": "target_abdomen",
                            "image_id": "img_venous",
                            "organ": "liver",
                            "path": output_buffer.relative_to(case_root).as_posix(),
                            "path_base": "package_root",
                            "sha256": prefixed_sha256(output_buffer),
                            "byte_count": output_buffer.stat().st_size,
                            "mimics_shape": list(liver_mask.shape),
                            "platform_shape": list(liver_mask.shape),
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
                    "target_ids": ["target_abdomen"],
                    "action": "submit_complete",
                    "assignee": "annotator_01",
                    "organ_outcomes": {"target_abdomen": {"liver": "present"}},
                }
            ),
            encoding="utf-8",
        )

        result = finalize_case(case_root, self.workstation_config(verified=True), registry_root)
        self.assertEqual("passed", result["status"])
        self.assertEqual(["liver"], [segment["organ"] for segment in result["records"][0]["segments"]])

    def test_known_absent_not_subset_of_organs_is_rejected(self) -> None:
        dicom_root = self.make_dicom_series()
        request = {
            "schema_version": "case_package_request.v1",
            "package_id": "pkg_case_003",
            "case_id": "case_003",
            "study_id": "study_003",
            "leakage_group_id": "patient_003",
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
                "review_id": "review_case_003_v1",
                "tool": "mimics",
                "assignee": "annotator_01",
                "targets": [
                    {
                        "target_id": "target_abdomen",
                        "image_id": "img_venous",
                        "organs": ["liver"],
                        "known_absent": ["spleen"],
                    }
                ],
            },
            "initial_labels": [],
        }
        request_path = self.root / "package_request_bad_known_absent.yaml"
        request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "known_absent must be a subset of organs"):
            create_case_package(request_path, self.root / "dataset_package_bad")

    def test_followup_review_adds_organ_without_discarding_existing_label(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        liver_mask = np.zeros(geometry.shape, dtype=np.uint8)
        liver_mask[1:4, 1:4, 1] = 1
        source_mask = self.root / "liver_initial.nii.gz"
        write_mask_nifti(source_mask, liver_mask, geometry)

        registry_root = self.root / "registry_followup"
        package_root = self.root / "followup_packages"
        case_root = create_case_package(
            self.make_request(dicom_root, source_mask),
            package_root,
            registry_root=registry_root,
        )
        runtime = load_data(prepare_case(case_root, self.workstation_config(verified=True)))
        base_target = runtime["targets"][0]
        submission_root = case_root / "submissions" / runtime["review_id"]
        output_buffer = submission_root / "buffers" / "img_venous" / "target_liver" / "liver.u8"
        output_buffer.parent.mkdir(parents=True)
        output_buffer.write_bytes(liver_mask.tobytes(order="C"))
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
                            "mimics_shape": list(liver_mask.shape),
                            "platform_shape": list(liver_mask.shape),
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
        first_result = finalize_case(case_root, self.workstation_config(verified=True), registry_root)
        liver_label_id = first_result["label_ids"][0]
        self.assertEqual("active", FileRegistry(registry_root).get("labels", liver_label_id)["artifact_lifecycle"])

        followup = create_followup_reviews(
            registry_root,
            package_root,
            organs=["spleen"],
            assignee="annotator_01",
            case_ids=["case_001"],
            review_suffix="add_spleen",
        )
        self.assertEqual(1, followup["review_count"])
        followup_root = Path(followup["results"][0]["package_path"])
        followup_runtime = load_data(prepare_case(followup_root, self.workstation_config(verified=True)))
        followup_target = followup_runtime["targets"][0]
        self.assertEqual(["spleen"], [mask["organ"] for mask in followup_target["masks"]])
        self.assertEqual(liver_label_id, followup_target["base_label_id"])

        spleen_mask = np.zeros(geometry.shape, dtype=np.uint8)
        spleen_mask[0:2, 0:2, 1] = 1
        followup_submission = followup_root / "submissions" / followup_runtime["review_id"]
        spleen_buffer = followup_submission / "buffers" / "img_venous" / followup_target["target_id"] / "spleen.u8"
        spleen_buffer.parent.mkdir(parents=True)
        spleen_buffer.write_bytes(spleen_mask.tobytes(order="C"))
        (followup_submission / "export_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "mimics_export_manifest.v1",
                    "review_id": followup_runtime["review_id"],
                    "mimics_version": "21.0",
                    "python_version": "3.5.2",
                    "entries": [
                        {
                            "target_id": followup_target["target_id"],
                            "image_id": "img_venous",
                            "organ": "spleen",
                            "path": spleen_buffer.relative_to(followup_root).as_posix(),
                            "path_base": "package_root",
                            "sha256": prefixed_sha256(spleen_buffer),
                            "byte_count": spleen_buffer.stat().st_size,
                            "mimics_shape": list(spleen_mask.shape),
                            "platform_shape": list(spleen_mask.shape),
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (followup_submission / "submission_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "review_submission.v1",
                    "review_id": followup_runtime["review_id"],
                    "target_ids": [followup_target["target_id"]],
                    "action": "submit_complete",
                    "assignee": "annotator_01",
                    "base_labels": {
                        followup_target["target_id"]: {
                            "label_id": liver_label_id,
                            "sha256": followup_target["base_label_sha256"],
                        }
                    },
                    "organ_outcomes": {followup_target["target_id"]: {"spleen": "present"}},
                }
            ),
            encoding="utf-8",
        )
        second_result = finalize_case(followup_root, self.workstation_config(verified=True), registry_root)
        combined_label = second_result["records"][0]
        self.assertEqual({"liver", "spleen"}, {segment["organ"] for segment in combined_label["segments"]})
        registry = FileRegistry(registry_root)
        self.assertEqual("superseded", registry.get("labels", liver_label_id)["artifact_lifecycle"])
        self.assertEqual(1, len(registry.find_labels(case_id="case_001", image_id="img_venous", organ="liver")))

    def test_create_followup_review_from_snapshot_finding(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        liver_mask = np.zeros(geometry.shape, dtype=np.uint8)
        liver_mask[1:4, 1:4, 1] = 1
        source_mask = self.root / "finding_liver_initial.nii.gz"
        write_mask_nifti(source_mask, liver_mask, geometry)

        registry_root = self.root / "registry_finding_followup"
        package_root = self.root / "finding_packages"
        create_case_package(
            self.make_request(dicom_root, source_mask),
            package_root,
            registry_root=registry_root,
        )
        finding_path = self.root / "snapshot_build_report.json"
        finding_path.write_text(
            json.dumps(
                {
                    "status": "built",
                    "skipped": [
                        {
                            "case_id": "case_001",
                            "image_id": "img_venous",
                            "reason": "missing_required_organs",
                            "missing_organs": ["spleen"],
                        },
                        {
                            "case_id": "case_001",
                            "image_id": "img_venous",
                            "reason": "leakage_conflict",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = create_followup_reviews_from_findings(
            registry_root,
            package_root,
            finding_path,
            assignee="annotator_02",
            review_suffix="snapshot_fix",
        )

        self.assertEqual(1, result["review_count"])
        self.assertEqual(1, len(result["unsupported"]))
        review = FileRegistry(registry_root).get("reviews", "review_case_001_snapshot_fix_01")
        self.assertEqual("annotator_02", review["assignee"])
        self.assertEqual(["spleen"], review["targets"][0]["organs"])
        self.assertEqual("img_venous", review["targets"][0]["image_id"])

    def test_export_worklist_and_collect_submission_for_assignee(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        source_mask = self.root / "liver.nii.gz"
        write_mask_nifti(source_mask, mask, geometry)

        registry_root = self.root / "registry_distribution"
        package_root = self.root / "central_packages"
        case_root = create_case_package(
            self.make_request(dicom_root, source_mask),
            package_root,
            registry_root=registry_root,
        )
        runtime_path = prepare_case(case_root, self.workstation_config(verified=True))
        runtime = load_data(runtime_path)

        worker_root = self.root / "worker_annotator_01"
        export = export_worklist(
            registry_root,
            worker_root,
            assignee="annotator_01",
            overwrite=True,
        )
        self.assertEqual(1, export["review_count"])
        self.assertFalse((worker_root / "registry").exists())
        worklist = load_data(worker_root / "worklist_manifest.json")
        self.assertEqual("mimics_worklist.v2", worklist["schema_version"])
        self.assertEqual("cases/case_001", worklist["reviews"][0]["package_path"])
        self.assertEqual("build_on_first_open", worklist["reviews"][0]["workspace_mode"])
        self.assertEqual(7, len(worklist["entry_scripts"]))
        self.assertTrue((worker_root / "Labeling_Open_Next_Case.py").is_file())
        self.assertTrue((worker_root / "Labeling_Case_Navigation.py").is_file())
        self.assertTrue((worker_root / "Labeling_Submit_Complete.py").is_file())
        self.assertTrue((worker_root / "Labeling_Submit_or_Report_Issue.py").is_file())
        self.assertTrue((worker_root / "Labeling_View_Task_List.py").is_file())
        self.assertTrue((worker_root / "nnInteractive.py").is_file())
        self.assertTrue((worker_root / "nninteractive_bridge.py").is_file())
        self.assertTrue((worker_root / "runtime_py35" / "nninteractive_mimics.py").is_file())
        self.assertFalse((worker_root / "Start_Labeling.py").exists())
        self.assertTrue((worker_root / "runtime_py35" / "sp_review_console.py").is_file())
        review_record = FileRegistry(registry_root).get("reviews", "review_case_001_v1")
        self.assertEqual(worklist["worklist_id"], review_record["worklist_exports"][0]["worklist_id"])
        with self.assertRaisesRegex(ValidationError, "no reviews matched"):
            export_worklist(
                registry_root,
                self.root / "second_worker",
                assignee="annotator_01",
            )
        self.assertFalse((self.root / "second_worker").exists())
        returned_case = worker_root / "cases" / "case_001"
        submission = returned_case / "submissions" / "review_case_001_v1"
        submission.mkdir(parents=True)
        (submission / "submission_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "review_submission.v1",
                    "review_id": "review_case_001_v1",
                    "target_ids": ["target_liver"],
                    "action": "report_blocked",
                    "assignee": "annotator_01",
                    "base_labels": {},
                    "organ_outcomes": {},
                    "reason_code": "wrong_image",
                }
            ),
            encoding="utf-8",
        )

        collected = collect_submissions(
            worker_root / "cases",
            case_root.parent,
            registry_root=registry_root,
            overwrite=True,
        )
        self.assertEqual("collected", collected["results"][0]["status"])
        self.assertTrue((case_root / "submissions" / "review_case_001_v1" / "submission_manifest.json").is_file())

    def test_snapshot_request_can_be_built_from_registry_labels(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        source_mask = self.root / "liver_for_snapshot.nii.gz"
        write_mask_nifti(source_mask, mask, geometry)

        registry_root = self.root / "registry_snapshot_request"
        create_case_package(
            self.make_request(dicom_root, source_mask),
            self.root / "snapshot_packages",
            registry_root=registry_root,
        )
        request_path = self.root / "snapshot_request.yaml"
        report = build_snapshot_request(
            registry_root,
            request_path,
            snapshot_id="snapshot_candidate_liver",
            task_id="liver_task",
            organs=["liver"],
            allow_lifecycle_status=["candidate_label"],
        )
        self.assertEqual(1, report["case_image_count"])
        request = load_data(request_path)
        self.assertEqual(["candidate_label"], request["label_policy"]["allow_lifecycle_status"])
        self.assertTrue(request["cases"][0]["segments"][0]["label_id"].startswith("label_img_venous_initial_"))

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
        scan = scan_source(dicom_root, workers=2)
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

    def test_build_requests_can_use_organs_file_and_unassigned_queue(self) -> None:
        dicom_root = self.make_dicom_series()
        scan = scan_source(dicom_root)
        scan_path = self.root / "scan_for_organs_file.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        organs_path = self.root / "target_organs.txt"
        organs_path.write_text("liver\nspleen\n", encoding="utf-8")

        from segplatform.cli import _load_organs_file

        batch = build_case_package_requests(
            scan_path,
            self.root / "requests_organs_file",
            organs=_load_organs_file(organs_path),
            import_batch="batch_organs_file",
            assignee=None,
        )

        request = load_data(Path(batch["requests"][0]))
        self.assertIsNone(request["review"]["assignee"])
        self.assertEqual(["liver", "spleen"], request["review"]["targets"][0]["organs"])

    def test_deidentification_findings_are_nonblocking_by_default(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        source_mask = self.root / "liver_deid_optional.nii.gz"
        write_mask_nifti(source_mask, np.zeros(geometry.shape, dtype=np.uint8), geometry)
        request = load_data(self.make_request(dicom_root, source_mask))
        request["data_governance"]["deidentification_status"] = "pending"
        request_path = self.root / "package_request_deid_pending.yaml"
        request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")

        case_root = create_case_package(request_path, self.root / "dataset_package_deid_pending")
        manifest = load_data(case_root / "manifest.json")
        self.assertEqual("pending", manifest["data_governance"]["deidentification_status"])
        report = load_data(case_root / "reports" / "ingest_report.json")
        self.assertIn(report["images"][0]["status"], {"passed", "warning"})

    def test_ingest_registers_images_without_creating_case_packages_or_reviews(self) -> None:
        dicom_root = self.make_dicom_series()
        scan = scan_source(dicom_root)
        scan_path = self.root / "scan_for_registry.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        registry_root = self.root / "asset_registry"

        result = register_scan(
            scan_path,
            registry_root,
            import_batch="batch_assets",
            source_type="dicom_inventory",
            source_name="pilot_dataset",
        )

        self.assertEqual(1, result["registered_cases"])
        self.assertEqual(1, result["registered_images"])
        registry = FileRegistry(registry_root)
        cases = registry.list("cases")
        images = registry.list("images")
        self.assertEqual(1, len(cases))
        self.assertEqual(1, len(images))
        self.assertEqual(cases[0]["image_ids"], [images[0]["image_id"]])
        self.assertEqual("dicom_inventory", images[0]["source"]["type"])
        self.assertEqual("batch_assets", images[0]["source"]["import_batch"])
        self.assertEqual("pilot_dataset", images[0]["source"]["name"])
        self.assertIn("source_files", images[0]["source"]["source_layout"])
        self.assertEqual([], registry.list("reviews"))
        self.assertFalse((self.root / "dataset_package").exists())

    def test_label_register_attaches_source_label_without_review(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        scan = scan_source(dicom_root)
        scan_path = self.root / "scan_for_label_register.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        registry_root = self.root / "label_register_registry"
        register_scan(scan_path, registry_root, import_batch="batch_assets")

        registry = FileRegistry(registry_root)
        case = registry.list("cases")[0]
        image_id = case["image_ids"][0]
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        mask[1:4, 1:4, 1] = 1
        mask_path = self.root / "external_liver.nii.gz"
        write_mask_nifti(mask_path, mask, geometry)

        result = register_label(
            registry_root,
            case_id=case["case_id"],
            image_id=image_id,
            mask_path=mask_path,
            organ="liver",
            lifecycle_status="source_label",
            source_type="imported_dataset",
            source_name="trusted_public_dataset",
            model_training="allowed_with_policy",
        )

        label = registry.get("labels", result["label_id"])
        self.assertEqual("source_label", label["segments"][0]["lifecycle_status"])
        self.assertEqual("imported_dataset", label["segments"][0]["source"]["type"])
        self.assertEqual("trusted_public_dataset", label["segments"][0]["source"]["name"])
        self.assertEqual([], registry.list("reviews"))

        snapshot_request = self.root / "snapshot_from_source_label.yaml"
        report = build_snapshot_request(
            registry_root,
            snapshot_request,
            snapshot_id="snapshot_source_liver",
            task_id="liver_task",
            organs=["liver"],
            allow_lifecycle_status=["source_label"],
        )
        self.assertEqual(1, report["case_image_count"])
        request = load_data(snapshot_request)
        self.assertEqual(result["label_id"], request["cases"][0]["segments"][0]["label_id"])

    def test_label_register_many_and_merge_label_artifacts(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        scan = scan_source(dicom_root)
        scan_path = self.root / "scan_for_label_merge.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        registry_root = self.root / "label_merge_registry"
        register_scan(scan_path, registry_root, import_batch="batch_assets")
        registry = FileRegistry(registry_root)
        case = registry.list("cases")[0]
        image_id = case["image_ids"][0]

        liver = np.zeros(geometry.shape, dtype=np.uint8)
        liver[1:4, 1:4, 1] = 1
        spleen = np.zeros(geometry.shape, dtype=np.uint8)
        spleen[0:2, 0:2, 1] = 1
        liver_path = self.root / "batch_liver.nii.gz"
        spleen_path = self.root / "batch_spleen.nii.gz"
        write_mask_nifti(liver_path, liver, geometry)
        write_mask_nifti(spleen_path, spleen, geometry)
        table_path = self.root / "labels.csv"
        table_path.write_text(
            "\n".join(
                [
                    "case_id,image_id,path,organ,lifecycle_status,model_training",
                    f"{case['case_id']},{image_id},{liver_path},liver,source_label,allowed",
                    f"{case['case_id']},{image_id},{spleen_path},spleen,source_label,needs_review",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        batch = register_labels_from_table(registry_root, table_path)
        self.assertEqual("registered", batch["status"])
        self.assertEqual(2, batch["registered_count"])

        merge = merge_labels(
            registry_root,
            label_ids=[item["label_id"] for item in batch["results"]],
            label_id="label_img_merged_test",
            supersede_inputs=True,
        )
        self.assertEqual("merged", merge["status"])
        merged = registry.get("labels", merge["label_id"])
        self.assertEqual({"liver", "spleen"}, {segment["organ"] for segment in merged["segments"]})
        self.assertEqual("needs_review", merged["usage_constraints"]["model_training"])
        for source_label_id in merge["input_label_ids"]:
            self.assertEqual("superseded", registry.get("labels", source_label_id)["artifact_lifecycle"])

    def test_label_merge_requires_explicit_organ_source_on_conflict(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        scan = scan_source(dicom_root)
        scan_path = self.root / "scan_for_label_conflict.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        registry_root = self.root / "label_conflict_registry"
        register_scan(scan_path, registry_root, import_batch="batch_assets")
        registry = FileRegistry(registry_root)
        case = registry.list("cases")[0]
        image_id = case["image_ids"][0]
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        mask[1:4, 1:4, 1] = 1
        first_path = self.root / "liver_a.nii.gz"
        second_path = self.root / "liver_b.nii.gz"
        write_mask_nifti(first_path, mask, geometry)
        write_mask_nifti(second_path, mask, geometry)
        first = register_label(
            registry_root,
            case_id=case["case_id"],
            image_id=image_id,
            mask_path=first_path,
            organ="liver",
            label_id="label_liver_a",
        )
        second = register_label(
            registry_root,
            case_id=case["case_id"],
            image_id=image_id,
            mask_path=second_path,
            organ="liver",
            label_id="label_liver_b",
        )

        with self.assertRaisesRegex(ValidationError, "organ liver appears in multiple labels"):
            merge_labels(registry_root, label_ids=[first["label_id"], second["label_id"]])

        resolved = merge_labels(
            registry_root,
            label_ids=[first["label_id"], second["label_id"]],
            organ_sources={"liver": second["label_id"]},
            label_id="label_liver_conflict_resolved",
        )
        self.assertEqual("label_liver_conflict_resolved", resolved["label_id"])

    def test_ingest_scan_discovers_nifti_without_manual_image_sets(self) -> None:
        source_root = self.root / "nifti_dataset" / "patient_a"
        source_root.mkdir(parents=True)
        image_path = source_root / "ct_venous.nii.gz"
        affine = np.diag([1.0, 1.5, 2.0, 1.0])
        image = nib.Nifti1Image(np.zeros((6, 5, 3), dtype=np.int16), affine)
        image.set_data_dtype(np.int16)
        nib.save(image, str(image_path))

        scan = scan_source(self.root / "nifti_dataset")
        self.assertEqual(1, scan["summary"]["importable_series_count"])
        self.assertEqual(1, scan["summary"]["file_image_count"])
        record = scan["series"][0]
        self.assertEqual("nifti", record["format"])
        self.assertEqual("source_path_group", record["leakage_group_basis"])

        scan_path = self.root / "nifti_scan.json"
        scan_path.write_text(json.dumps(scan), encoding="utf-8")
        requests_dir = self.root / "nifti_requests"
        batch = build_case_package_requests(
            scan_path,
            requests_dir,
            organs=["liver"],
            import_batch="nifti_batch",
            assignee="annotator_01",
        )
        request = load_data(Path(batch["requests"][0]))
        self.assertEqual("nifti", request["image_sets"][0]["format"])
        self.assertEqual(str(image_path.resolve()), request["image_sets"][0]["source"])
        self.assertNotIn("source_files", request["image_sets"][0])

        case_root = create_case_package(Path(batch["requests"][0]), self.root / "nifti_package")
        manifest = load_data(case_root / "manifest.json")
        self.assertIn("image_path", manifest["image_sets"][0])
        self.assertIn("dicom_path", manifest["image_sets"][0])
        self.assertIn("dicom_sha256", manifest["image_sets"][0])
        self.assertEqual("derived_dicom_series", manifest["image_sets"][0]["mimics_import"]["strategy"])
        self.assertEqual("RAS", manifest["image_sets"][0]["coordinate_system"])
        original_geometry, _ = inspect_image(case_root / manifest["image_sets"][0]["image_path"], "nifti")
        derived_geometry, _ = inspect_image(case_root / manifest["image_sets"][0]["dicom_path"], "dicom_series")
        matches, reasons = geometry_matches(original_geometry, derived_geometry)
        self.assertTrue(matches, reasons)
        runtime = load_data(prepare_case(case_root, self.workstation_config(verified=True)))
        self.assertEqual("new", runtime["mode"])
        self.assertTrue(runtime["image_sets"][0]["dicom_path"].endswith("/dicom"))

    def test_dataset_description_discovers_per_organ_labels(self) -> None:
        dataset_root = self.root / "totalseg_like"
        case_root = dataset_root / "case001"
        labels_root = case_root / "segmentations"
        labels_root.mkdir(parents=True)
        affine = np.diag([1.0, 1.0, 2.0, 1.0])
        image_path = case_root / "ct.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((6, 5, 3), dtype=np.int16), affine), str(image_path))
        liver = np.zeros((6, 5, 3), dtype=np.uint8)
        liver[1:3, 1:3, 1] = 1
        spleen = np.zeros((6, 5, 3), dtype=np.uint8)
        spleen[3:5, 2:4, 1] = 1
        nib.save(nib.Nifti1Image(liver, affine), str(labels_root / "liver.nii.gz"))
        nib.save(nib.Nifti1Image(spleen, affine), str(labels_root / "spleen.nii.gz"))

        description = {
            "schema_version": "dataset_description.v1",
            "dataset_id": "totalseg_like",
            "root": str(dataset_root),
            "defaults": {
                "organs": ["liver", "spleen"],
                "modality": "CT",
                "import_batch": "totalseg_batch",
                "assignee": "annotator_01",
            },
            "discovery": {
                "images": [
                    {
                        "regex": r"(?P<case>[^/]+)/ct\.nii\.gz",
                        "case_id": "case_{case}",
                        "study_id": "study_{case}",
                        "image_id": "img_{case}",
                        "format": "nifti",
                    }
                ],
                "labels": [
                    {
                        "regex": r"(?P<case>[^/]+)/segmentations/(?P<organ>liver|spleen)\.nii\.gz",
                        "type": "per_organ",
                        "image_id": "img_{case}",
                        "organ": "{organ}",
                        "lifecycle_status": "source_label",
                    }
                ],
            },
        }
        description_path = self.root / "totalseg_description.yaml"
        description_path.write_text(yaml.safe_dump(description, sort_keys=False), encoding="utf-8")
        batch = build_requests_from_dataset_description(description_path, self.root / "totalseg_requests")
        self.assertEqual(1, batch["request_count"])
        request = load_data(Path(batch["requests"][0]))
        self.assertEqual(2, len(request["initial_labels"]))
        self.assertEqual({"liver", "spleen"}, {item["organ"] for item in request["initial_labels"]})

        package_root = create_case_package(Path(batch["requests"][0]), self.root / "totalseg_package")
        manifest = load_data(package_root / "manifest.json")
        self.assertEqual(2, len(manifest["initial_labels"]))
        self.assertEqual({"liver", "spleen"}, {item["organ"] for item in manifest["initial_labels"]})

    def test_dataset_description_discovers_multilabel_label_map(self) -> None:
        dataset_root = self.root / "msd_like"
        images_root = dataset_root / "imagesTr"
        labels_root = dataset_root / "labelsTr"
        images_root.mkdir(parents=True)
        labels_root.mkdir()
        affine = np.diag([1.0, 1.0, 1.5, 1.0])
        image_path = images_root / "case001.nii.gz"
        label_path = labels_root / "case001.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((6, 5, 3), dtype=np.int16), affine), str(image_path))
        label = np.zeros((6, 5, 3), dtype=np.uint8)
        label[1:3, 1:3, 1] = 1
        label[3:5, 2:4, 1] = 2
        nib.save(nib.Nifti1Image(label, affine), str(label_path))

        description = {
            "schema_version": "dataset_description.v1",
            "dataset_id": "msd_like",
            "root": str(dataset_root),
            "defaults": {
                "organs": ["liver", "spleen"],
                "modality": "CT",
                "import_batch": "msd_batch",
            },
            "discovery": {
                "images": [
                    {
                        "regex": r"imagesTr/(?P<case>[^/]+)\.nii\.gz",
                        "case_id": "case_{case}",
                        "study_id": "study_{case}",
                        "image_id": "img_{case}",
                        "format": "nifti",
                    }
                ],
                "labels": [
                    {
                        "regex": r"labelsTr/(?P<case>[^/]+)\.nii\.gz",
                        "type": "multilabel",
                        "image_id": "img_{case}",
                        "label_map": {"liver": 1, "spleen": 2},
                        "lifecycle_status": "source_label",
                    }
                ],
            },
        }
        description_path = self.root / "msd_description.yaml"
        description_path.write_text(yaml.safe_dump(description, sort_keys=False), encoding="utf-8")
        batch = build_requests_from_dataset_description(description_path, self.root / "msd_requests")
        request = load_data(Path(batch["requests"][0]))
        self.assertEqual({"liver": 1, "spleen": 2}, request["initial_labels"][0]["label_map"])

        package_root = create_case_package(Path(batch["requests"][0]), self.root / "msd_package")
        manifest = load_data(package_root / "manifest.json")
        self.assertEqual({"liver", "spleen"}, {item["organ"] for item in manifest["initial_labels"]})

    def test_review_next_skips_submitted_pending_but_returns_failed_qc(self) -> None:
        registry_root = self.root / "registry"
        case_root = self.root / "dataset_package" / "cases" / "case_001"
        case_root.mkdir(parents=True)
        record = {
            "schema_version": "review_task.v1",
            "review_id": "review_case_001",
            "package_id": "pkg_case_001",
            "case_id": "case_001",
            "tool": "mimics",
            "status": "in_progress",
            "assignee": "annotator_01",
            "package_path": str(case_root),
            "created_at": "2026-06-16T00:00:00+00:00",
            "targets": [
                {
                    "target_id": "target_liver",
                    "image_id": "img_venous",
                    "organs": ["liver"],
                    "status": "in_progress",
                }
            ],
            "events": [],
        }
        registry = FileRegistry(registry_root)
        registry.put("reviews", record)
        self.assertEqual("review_case_001", next_review(registry_root, assignee="annotator_01")["review_id"])
        next_case_root = self.root / "dataset_package" / "cases" / "case_002"
        next_case_root.mkdir(parents=True)
        second_record = {
            **record,
            "review_id": "review_case_002",
            "case_id": "case_002",
            "status": "ready",
            "package_path": str(next_case_root),
            "created_at": "2026-06-16T00:01:00+00:00",
            "targets": [{**record["targets"][0], "status": "ready"}],
        }
        registry.put("reviews", second_record)
        self.assertEqual(
            "review_case_002",
            next_review(
                registry_root,
                assignee="annotator_01",
                exclude_review_id="review_case_001",
            )["review_id"],
        )
        second_record["status"] = "completed"
        registry.put("reviews", second_record, allow_update=True)

        submission = case_root / "submissions" / "review_case_001" / "submission_manifest.json"
        submission.parent.mkdir(parents=True)
        submission.write_text(json.dumps({"schema_version": "review_submission.v1"}), encoding="utf-8")
        self.assertEqual("empty", next_review(registry_root, assignee="annotator_01")["status"])

        report = case_root / "reports" / "review_report.json"
        report.parent.mkdir()
        report.write_text(json.dumps({"schema_version": "review_report.v1", "status": "failed"}), encoding="utf-8")
        os.utime(submission, (1000, 1000))
        os.utime(report, (2000, 2000))
        self.assertEqual("review_case_001", next_review(registry_root, assignee="annotator_01")["review_id"])

        submission.write_text(json.dumps({"schema_version": "review_submission.v1", "attempt": 2}), encoding="utf-8")
        os.utime(submission, (3000, 3000))
        self.assertEqual("empty", next_review(registry_root, assignee="annotator_01")["status"])

    def test_deferred_review_leaves_queue_without_blocking(self) -> None:
        registry_root = self.root / "registry_defer"
        case_root = self.root / "dataset_package" / "cases" / "case_defer"
        case_root.mkdir(parents=True)
        record = {
            "schema_version": "review_task.v1",
            "review_id": "review_defer",
            "package_id": "pkg_defer",
            "case_id": "case_defer",
            "tool": "mimics",
            "status": "ready",
            "assignee": "annotator_01",
            "package_path": str(case_root),
            "created_at": "2026-01-01T00:00:00+00:00",
            "targets": [
                {
                    "target_id": "target_liver",
                    "image_id": "img_ct",
                    "organs": ["liver"],
                    "status": "ready",
                }
            ],
            "events": [],
        }
        registry = FileRegistry(registry_root)
        registry.put("reviews", record)
        self.assertEqual("review_defer", next_review(registry_root, assignee="annotator_01")["review_id"])
        defer_review(registry_root, "review_defer", actor="annotator_01", reason="not_today")
        self.assertEqual("empty", next_review(registry_root, assignee="annotator_01")["status"])
        self.assertEqual("deferred", registry.get("reviews", "review_defer")["status"])
        reactivate_review(registry_root, "review_defer", actor="lead")
        self.assertEqual("review_defer", next_review(registry_root, assignee="annotator_01")["review_id"])

    def test_unassigned_review_can_be_claimed_and_reassigned_without_rebuilding_package(self) -> None:
        registry_root = self.root / "registry_claim"
        case_root = self.root / "dataset_package" / "cases" / "case_claim"
        case_root.mkdir(parents=True)
        record = {
            "schema_version": "review_task.v1",
            "review_id": "review_claim",
            "package_id": "pkg_claim",
            "case_id": "case_claim",
            "tool": "mimics",
            "status": "ready",
            "assignee": None,
            "package_path": str(case_root),
            "created_at": "2026-01-01T00:00:00+00:00",
            "targets": [
                {
                    "target_id": "target_liver",
                    "image_id": "img_ct",
                    "organs": ["liver"],
                    "status": "ready",
                }
            ],
            "events": [],
        }
        registry = FileRegistry(registry_root)
        registry.put("reviews", record)

        self.assertEqual("empty", next_review(registry_root, assignee="annotator_01")["status"])
        claimed = next_review(registry_root, assignee="annotator_01", claim_unassigned=True)
        self.assertEqual("review_claim", claimed["review_id"])
        self.assertEqual("annotator_01", FileRegistry(registry_root).get("reviews", "review_claim")["assignee"])

        assigned = assign_review(registry_root, "review_claim", assignee="annotator_02", actor="lead")
        self.assertEqual("annotator_02", assigned["assignee"])
        self.assertEqual("empty", next_review(registry_root, assignee="annotator_01")["status"])
        self.assertEqual("review_claim", next_review(registry_root, assignee="annotator_02")["review_id"])

    def test_export_worklist_can_claim_unassigned_reviews(self) -> None:
        registry_root = self.root / "registry_worklist_claim"
        case_root = self.root / "central_cases_claim" / "case_claim"
        case_root.mkdir(parents=True)
        (case_root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "case_package.v0.5",
                    "package_id": "pkg_claim",
                    "case_id": "case_claim",
                    "review": {"review_id": "review_claim"},
                }
            ),
            encoding="utf-8",
        )
        registry = FileRegistry(registry_root)
        registry.put(
            "cases",
            {
                "schema_version": "case_manifest.v1",
                "case_id": "case_claim",
                "leakage_group_id": "subject_claim",
                "leakage_group_basis": "case",
                "leakage_group_confidence": "low",
                "study_id": "study_claim",
                "image_ids": ["img_ct"],
                "data_governance": {"deidentification_status": "pending"},
            },
        )
        registry.put(
            "images",
            {
                "schema_version": "image_artifact.v1",
                "image_id": "img_ct",
                "case_id": "case_claim",
                "modality": "CT",
                "format": "dicom_series",
                "path": str(case_root / "images" / "img_ct" / "dicom"),
                "hash": "sha256:" + "0" * 64,
                "hash_scope": "bundle_manifest",
                "pixel_type": "int16",
                "shape": [2, 2, 2],
                "spacing": [1.0, 1.0, 1.0],
                "origin": [0.0, 0.0, 0.0],
                "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "geometry_status": "complete",
                "geometry_evidence": {
                    "coordinate_system": "LPS",
                    "shape": "header",
                    "spacing": "header",
                    "origin": "header",
                    "direction": "header",
                    "assumptions": [],
                },
                "source": {
                    "type": "test",
                    "import_batch": "test",
                    "reader": {"name": "test", "version": "1"},
                },
                "usability": {"annotation": "allowed", "training": "allowed", "evaluation": "allowed", "reasons": []},
            },
        )
        registry.put(
            "reviews",
            {
                "schema_version": "review_task.v1",
                "review_id": "review_claim",
                "package_id": "pkg_claim",
                "case_id": "case_claim",
                "tool": "mimics",
                "status": "ready",
                "assignee": None,
                "package_path": str(case_root),
                "created_at": "2026-01-01T00:00:00+00:00",
                "targets": [
                    {
                        "target_id": "target_liver",
                        "image_id": "img_ct",
                        "organs": ["liver"],
                        "status": "ready",
                    }
                ],
                "events": [],
            },
        )
        working = case_root / "working"
        working.mkdir()
        mcs_path = working / "review_claim.mcs"
        mcs_path.touch()
        (working / "mimics_runtime.json").write_text(
            json.dumps(
                {
                    "schema_version": "mimics_runtime.v1",
                    "package_root": str(case_root),
                    "package_id": "pkg_claim",
                    "case_id": "case_claim",
                    "review_id": "review_claim",
                    "mcs_path": str(mcs_path),
                }
            ),
            encoding="utf-8",
        )

        mismatched_runtime = load_data(working / "mimics_runtime.json")
        mismatched_runtime["review_id"] = "review_wrong"
        write_json(working / "mimics_runtime.json", mismatched_runtime)
        with self.assertRaisesRegex(ValidationError, "identity mismatch"):
            export_worklist(
                registry_root,
                self.root / "worker_mismatch",
                assignee="annotator_01",
                claim_unassigned=True,
                overwrite=True,
            )
        self.assertFalse((self.root / "worker_mismatch").exists())
        mismatched_runtime["review_id"] = "review_claim"
        write_json(working / "mimics_runtime.json", mismatched_runtime)

        def fail_manifest_publish(path: Path, value: object) -> None:
            if path.name == "worklist_manifest.json":
                raise OSError("simulated manifest publish failure")
            write_json(path, value)

        with (
            patch("segplatform.distribution.write_json", side_effect=fail_manifest_publish),
            self.assertRaisesRegex(OSError, "simulated manifest publish failure"),
        ):
            export_worklist(
                registry_root,
                self.root / "worker_publish_failure",
                assignee="annotator_01",
                claim_unassigned=True,
                overwrite=True,
            )
        rolled_back = FileRegistry(registry_root).get("reviews", "review_claim")
        self.assertIsNone(rolled_back["assignee"])
        self.assertFalse(rolled_back.get("worklist_exports"))
        self.assertFalse(
            (self.root / "worker_publish_failure" / "worklist_manifest.json").exists()
        )

        export = export_worklist(
            registry_root,
            self.root / "worker_claim",
            assignee="annotator_01",
            claim_unassigned=True,
            overwrite=True,
        )

        self.assertEqual(1, export["review_count"])
        self.assertEqual("annotator_01", FileRegistry(registry_root).get("reviews", "review_claim")["assignee"])
        self.assertFalse((self.root / "worker_claim" / "registry").exists())
        self.assertEqual(
            "annotator_01",
            load_data(self.root / "worker_claim" / "worklist_manifest.json")["recipient_hint"],
        )

        with self.assertRaisesRegex(ValidationError, "--claim-unassigned requires --assignee"):
            export_worklist(
                registry_root,
                self.root / "invalid_claim",
                claim_unassigned=True,
            )

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
        responses = iter(["[ ] 1", "[ ] 3", "Use Selected", "All Confirmed Absent", "Continue Export"])
        dialog_calls: list[dict] = []

        class Dialogs:
            @staticmethod
            def question_box(**kwargs):
                dialog_calls.append(kwargs)
                return next(responses)

            @staticmethod
            def message_box(*_args, **_kwargs):
                return None

        fake_mimics = types.SimpleNamespace(dialogs=Dialogs(), data=types.SimpleNamespace(masks=[]))
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

        self.assertEqual("submit_complete", module.normalize_action("submit_complete"))
        with self.assertRaisesRegex(RuntimeError, "Unsupported submit action"):
            module.normalize_action("unsupported")

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

        class Metadata:
            def __init__(self, values):
                self.values = values

            def find(self, name):
                value = self.values.get(name)
                return None if value is None else types.SimpleNamespace(value=value)

        fake_mimics.data.masks = [
            types.SimpleNamespace(name="scratch_spleen", metadata=Metadata({})),
            types.SimpleNamespace(name="SP__target_a__liver", metadata=Metadata({"sp.review_id": "review_001"})),
        ]
        reports_dir = self.root / "reports_unmanaged"
        self.assertTrue(module.confirm_unmanaged_masks_ignored({"reports_dir": str(reports_dir)}))
        self.assertTrue((reports_dir / "mimics_unmanaged_masks.txt").is_file())
        self.assertIn("scratch_spleen", (reports_dir / "mimics_unmanaged_masks.txt").read_text(encoding="utf-8"))
        self.assertIn("will NOT be exported", dialog_calls[-1]["message"])

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

    def test_review_console_rebases_a_movable_worklist_runtime(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"

        class Dialogs:
            @staticmethod
            def question_box(**_kwargs):
                return "Cancel"

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
        spec = importlib.util.spec_from_file_location(
            "sp_review_console_qc_message_test", runtime_dir / "sp_review_console.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        old_root = self.root / "central" / "case_001"
        new_root = self.root / "copied_anywhere" / "case_001"
        runtime = {
            "package_root": str(old_root),
            "mcs_path": str(old_root / "working" / "review_001.mcs"),
            "reports_dir": str(old_root / "reports"),
            "submissions_dir": str(old_root / "submissions" / "review_001"),
            "image_sets": [
                {
                    "dicom_path": str(old_root / "images" / "img" / "dicom"),
                    "image_path": None,
                }
            ],
            "import_buffers": [
                {"path": str(old_root / "working" / "bridge" / "liver.u8")}
            ],
            "checkpoint_buffers": [],
        }

        rebased = module.rebase_runtime(runtime, str(new_root), "worklist_001")

        self.assertEqual(str(new_root), rebased["package_root"])
        self.assertEqual(str(new_root / "working" / "review_001.mcs"), rebased["mcs_path"])
        self.assertEqual(str(new_root / "reports"), rebased["reports_dir"])
        self.assertEqual(
            str(new_root / "images" / "img" / "dicom"),
            rebased["image_sets"][0]["dicom_path"],
        )
        self.assertIsNone(rebased["assignee"])
        self.assertEqual("worklist_001", rebased["worklist_id"])
        self.assertEqual("new", rebased["mode"])

        worklist_root = self.root / "worklist"
        entry = {
            "review_id": "review_001",
            "package_path": "cases/case_001",
        }
        submission_root = worklist_root / "cases" / "case_001" / "submissions" / "review_001"
        submission_root.mkdir(parents=True)
        submission_path = submission_root / "submission_manifest.json"
        submission_path.write_text(
            json.dumps({"worklist_id": "older_worklist", "action": "submit_complete"}),
            encoding="utf-8",
        )
        manifest = {"worklist_id": "worklist_001", "reviews": [entry]}
        state = {"items": {}}
        module.refresh_worklist_state(str(worklist_root), manifest, state)
        self.assertEqual("available", state["items"]["review_001"]["status"])

        submission_path.write_text(
            json.dumps({"worklist_id": "worklist_001", "action": "submit_complete"}),
            encoding="utf-8",
        )
        module.refresh_worklist_state(str(worklist_root), manifest, state)
        self.assertEqual("submitted", state["items"]["review_001"]["status"])

        state["items"]["review_001"].update(
            {
                "status": "in_progress",
                "last_submitted_at": "2026-06-24T10:00:00Z",
                "last_opened_at": "2026-06-24T11:00:00Z",
            }
        )
        module.refresh_worklist_state(str(worklist_root), manifest, state)
        self.assertEqual("in_progress", state["items"]["review_001"]["status"])

        submission_path.write_text(
            json.dumps(
                {
                    "worklist_id": "worklist_001",
                    "submission_id": "submission_new",
                    "action": "submit_complete",
                }
            ),
            encoding="utf-8",
        )
        module.refresh_worklist_state(str(worklist_root), manifest, state)
        self.assertEqual("submitted", state["items"]["review_001"]["status"])
        self.assertEqual(
            "submission_new",
            state["items"]["review_001"]["last_submission_key"],
        )

        mcs_path = new_root / "working" / "review_001.mcs"
        mcs_path.parent.mkdir(parents=True)
        mcs_path.write_bytes(b"project")
        runtime["prebuilt_marker_path"] = str(new_root / "working" / "prebuilt_workspace.json")
        resumed = module.rebase_runtime(runtime, str(new_root), "worklist_001")
        self.assertEqual("resume", resumed["mode"])

        marker_path = new_root / "working" / "prebuilt_workspace.json"
        marker_path.write_text("{}", encoding="utf-8")
        prebuilt = module.rebase_runtime(runtime, str(new_root), "worklist_001")
        self.assertEqual("prebuilt", prebuilt["mode"])

    def test_review_console_direct_submit_entry_has_no_action_menu(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"

        class Dialogs:
            @staticmethod
            def question_box(**_kwargs):
                raise AssertionError("direct submit must not show an action-selection menu")

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
        spec = importlib.util.spec_from_file_location(
            "sp_review_console_direct_action_test", runtime_dir / "sp_review_console.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        recorded = []
        module.load_worklist = lambda: (str(self.root), {"worklist_id": "worklist_001", "reviews": []})
        module.load_worklist_state = lambda _root, _manifest: (
            str(self.root / "worklist_progress.json"),
            {"current_review_id": "review_001", "items": {}},
        )
        module.refresh_worklist_state = lambda _root, _manifest, state: state
        module.current_review_context = lambda: {
            "review_id": "review_001",
            "package_root": str(self.root / "case_001"),
        }
        module.submit_current_review = (
            lambda _root, _manifest, _state_path, _state, action: recorded.append(action) or 0
        )

        self.assertEqual(0, module.main("submit_complete"))
        self.assertEqual(["submit_complete"], recorded)

    def test_review_console_groups_only_related_secondary_actions(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"
        responses = iter(["Continue Last Case", "Choose Case", "Skip Case", "Needs Review", "Report Problem"])

        class Dialogs:
            @staticmethod
            def question_box(**_kwargs):
                return next(responses)

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
        spec = importlib.util.spec_from_file_location(
            "sp_review_console_grouped_actions_test", runtime_dir / "sp_review_console.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        self.assertEqual("continue", module.choose_navigation_action(None, True))
        self.assertEqual("choose", module.choose_navigation_action(None, False))
        self.assertEqual("skip", module.choose_navigation_action({"review_id": "review_001"}, False))
        self.assertEqual("submit_for_review", module.choose_issue_action())
        self.assertEqual("report_blocked", module.choose_issue_action())

    def test_review_console_summary_reports_mask_state(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"
        messages: list[str] = []

        class Metadata:
            def __init__(self, values):
                self.values = values

            def find(self, name):
                value = self.values.get(name)
                return None if value is None else types.SimpleNamespace(value=value)

        mask = types.SimpleNamespace(
            name="SP__target_abdomen__liver",
            metadata=Metadata(
                {
                    "sp.review_id": "review_001",
                    "sp.target_id": "target_abdomen",
                    "sp.image_id": "img_ct",
                    "sp.organ": "liver",
                    "sp.package_root": str(self.root),
                }
            ),
        )

        class Dialogs:
            @staticmethod
            def message_box(message, **_kwargs):
                messages.append(message)

        fake_mimics = types.SimpleNamespace(data=types.SimpleNamespace(masks=[mask]), dialogs=Dialogs())
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
        spec = importlib.util.spec_from_file_location(
            "sp_review_console_test", runtime_dir / "sp_review_console.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        working = self.root / "working"
        working.mkdir()
        (working / "mimics_runtime.json").write_text(
            json.dumps(
                {
                    "review_id": "review_001",
                    "case_id": "case_001",
                    "targets": [
                        {
                            "target_id": "target_abdomen",
                            "image_id": "img_ct",
                            "organs": ["liver", "spleen", "kidney_left"],
                            "known_absent": ["kidney_left"],
                        }
                    ],
                    "import_buffers": [{"image_id": "img_ct", "organ": "liver"}],
                }
            ),
            encoding="utf-8",
        )

        module.show_current_summary({"package_root": str(self.root)})
        summary = messages[-1]
        self.assertIn("Organs: 3; ready masks: 1; missing masks: 1; known absent: 1", summary)
        self.assertIn("liver [mask ready, initial/checkpoint]", summary)
        self.assertIn("spleen [mask missing]", summary)
        self.assertIn("kidney_left [not required: known absent]", summary)

    def test_review_console_task_list_pages_and_filters(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"
        dialogs: list[tuple[str, str]] = []
        responses = iter(["Next Page", "Filter", "Missing", "Next Page", "Close"])

        class Metadata:
            def __init__(self, values):
                self.values = values

            def find(self, name):
                value = self.values.get(name)
                return None if value is None else types.SimpleNamespace(value=value)

        masks = []
        for organ in ("organ_00", "organ_01"):
            masks.append(
                types.SimpleNamespace(
                    name=f"SP__target_large__{organ}",
                    metadata=Metadata(
                        {
                            "sp.review_id": "review_large",
                            "sp.target_id": "target_large",
                            "sp.image_id": "img_ct",
                            "sp.organ": organ,
                            "sp.package_root": str(self.root),
                        }
                    ),
                )
            )

        class Dialogs:
            @staticmethod
            def question_box(message, buttons, **_kwargs):
                dialogs.append((message, buttons))
                return next(responses)

        fake_mimics = types.SimpleNamespace(data=types.SimpleNamespace(masks=masks), dialogs=Dialogs())
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
        spec = importlib.util.spec_from_file_location(
            "sp_review_console_task_list_test", runtime_dir / "sp_review_console.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        organs = [f"organ_{index:02d}" for index in range(25)]
        working = self.root / "working"
        reports = self.root / "reports"
        working.mkdir()
        reports.mkdir()
        (working / "mimics_runtime.json").write_text(
            json.dumps(
                {
                    "review_id": "review_large",
                    "case_id": "case_large",
                    "reports_dir": str(reports),
                    "targets": [
                        {
                            "target_id": "target_large",
                            "image_id": "img_ct",
                            "organs": organs,
                            "known_absent": [],
                        }
                    ],
                    "import_buffers": [{"image_id": "img_ct", "organ": "organ_00"}],
                }
            ),
            encoding="utf-8",
        )

        module.show_current_summary({"package_root": str(self.root)})

        page_messages = [message for message, buttons in dialogs if "Filter:" in message]
        filter_messages = [message for message, buttons in dialogs if message == "Show which organs?"]
        self.assertTrue(filter_messages)
        self.assertIn("Filter: All; Page 1/2; Showing 1-20 of 25", page_messages[0])
        self.assertIn("Filter: All; Page 2/2; Showing 21-25 of 25", page_messages[1])
        self.assertIn("Filter: Missing; Page 1/2; Showing 1-20 of 23", page_messages[2])
        self.assertIn("Filter: Missing; Page 2/2; Showing 21-23 of 23", page_messages[3])
        self.assertIn("organ_24 [mask missing]", page_messages[3])
        self.assertTrue((reports / "mimics_task_list.txt").is_file())

    def test_checkpoint_buffer_roundtrip_uses_gzip_snapshot(self) -> None:
        runtime_dir = Path(__file__).resolve().parents[1] / "adapters" / "mimics" / "runtime_py35"
        if str(runtime_dir) not in sys.path:
            sys.path.insert(0, str(runtime_dir))
            self.addCleanup(lambda: sys.path.remove(str(runtime_dir)))
        import sp_common

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

    def test_checkpoint_cleanup_keeps_latest_recovery_backups(self) -> None:
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
        spec = importlib.util.spec_from_file_location(
            "sp_save_checkpoint_test", runtime_dir / "sp_save_checkpoint.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        root = self.root / "case"
        checkpoints = root / "working" / "checkpoints" / "review_001"
        for name in ["20260601T000000Z_1", "20260602T000000Z_1", "20260603T000000Z_1", "20260604T000000Z_1"]:
            directory = checkpoints / name
            directory.mkdir(parents=True)
            (directory / "checkpoint_manifest.json").write_text("{}", encoding="utf-8")
        (checkpoints / "latest.json").write_text("{}", encoding="utf-8")

        removed = module.cleanup_old_checkpoints(
            {"package_root": str(root), "review_id": "review_001"},
            2,
        )
        self.assertEqual(2, len(removed))
        self.assertFalse((checkpoints / "20260601T000000Z_1").exists())
        self.assertFalse((checkpoints / "20260602T000000Z_1").exists())
        self.assertTrue((checkpoints / "20260603T000000Z_1").exists())
        self.assertTrue((checkpoints / "20260604T000000Z_1").exists())
        self.assertTrue((checkpoints / "latest.json").exists())

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
        marker_path = Path(prepared["prebuilt_marker_path"])
        mcs_path.write_bytes(b"prebuilt")
        marker_path.write_text(
            json.dumps(
                {
                    "schema_version": "mimics_prebuilt_workspace.v1",
                    "review_id": prepared["review_id"],
                    "mcs_path": str(mcs_path),
                    "status": "prebuilt",
                }
            ),
            encoding="utf-8",
        )
        prebuilt = load_data(prepare_case(case_root, config_path))
        self.assertEqual("prebuilt", prebuilt["mode"])
        self.assertEqual(str(marker_path), prebuilt["prebuilt_marker_path"])

        already_prebuilt = prebuild_workspace(case_root, config_path, dry_run=True)
        self.assertEqual("already_prebuilt", already_prebuilt["status"])
        self.assertFalse(already_prebuilt["started"])

        marker_path.unlink()
        already_existing = prebuild_workspace(case_root, config_path, dry_run=True)
        self.assertEqual("already_exists", already_existing["status"])
        self.assertIn("--rebuild-workspace", already_existing["reason"])
        self.assertFalse(already_existing["started"])

        mcs_path.write_bytes(b"damaged")
        rebuilt = load_data(prepare_case(case_root, config_path, rebuild_workspace=True))
        self.assertEqual("new", rebuilt["mode"])
        self.assertFalse(mcs_path.exists())
        self.assertFalse(marker_path.exists())
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

    def test_initial_label_rejects_simultaneous_organ_and_label_map(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        mask = np.zeros(geometry.shape, dtype=np.uint8)
        mask[1:4, 1:4, 1] = 1
        source_mask = self.root / "ambig.nii.gz"
        write_mask_nifti(source_mask, mask, geometry)
        request = load_data(self.make_request(dicom_root, source_mask))
        request["initial_labels"][0]["label_map"] = {"liver": 1}
        request_path = self.root / "ambig_request.yaml"
        request_path.write_text(yaml.safe_dump(request, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "both 'organ' and 'label_map'"):
            create_case_package(request_path, self.root / "ambig_package")

    def test_ingest_warns_when_one_study_has_multiple_patient_ids(self) -> None:
        series_root = self.make_dicom_series()
        second_slice = sorted(series_root.glob("*.dcm"))[1]
        dataset = pydicom.dcmread(second_slice)
        dataset.PatientID = "PSEUDO_OTHER"
        dataset.save_as(second_slice, enforce_file_format=True)
        scan = scan_source(series_root)
        self.assertTrue(scan["findings"])
        self.assertEqual("study_with_multiple_patient_ids", scan["findings"][0]["code"])
        self.assertEqual(1, scan["summary"]["finding_count"])

    def test_snapshot_require_all_organs_rejects_missing_organ(self) -> None:
        dicom_root = self.make_dicom_series()
        geometry, _ = inspect_dicom_series(dicom_root)
        source_mask = self.root / "liver_only.nii.gz"
        write_mask_nifti(source_mask, np.zeros(geometry.shape, dtype=np.uint8), geometry)
        registry_root = self.root / "registry_require_all"
        create_case_package(
            self.make_request(dicom_root, source_mask),
            self.root / "require_all_package",
            registry_root=registry_root,
        )
        registry = FileRegistry(registry_root)
        liver_label_id = registry.find_labels(case_id="case_001", image_id="img_venous", organ="liver")[0]["label_id"]
        snapshot_request = {
            "schema_version": "snapshot_request.v1",
            "snapshot_id": "snapshot_require_all",
            "task_id": "abdomen_task",
            "task_label_map": {"background": 0, "liver": 1, "spleen": 2},
            "label_policy": {"allow_lifecycle_status": ["candidate_label"]},
            "require_all_organs": True,
            "cases": [
                {
                    "case_id": "case_001",
                    "image_id": "img_venous",
                    "split": "train",
                    "segments": [{"organ": "liver", "label_id": liver_label_id}],
                }
            ],
            "preprocess_profile": {"name": "none"},
            "usage_constraints": {
                "model_training": "allowed",
                "commercial_use": "needs_policy",
                "redistribution": "needs_policy",
            },
        }
        snapshot_request_path = self.root / "snapshot_require_all.yaml"
        snapshot_request_path.write_text(yaml.safe_dump(snapshot_request, sort_keys=False), encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "requires all organs but is missing"):
            create_snapshot(snapshot_request_path, registry_root)

    def test_derived_dicom_series_uids_are_deterministic(self) -> None:
        from segplatform.imaging import write_derived_dicom_series

        affine = np.diag([1.0, 1.5, 2.0, 1.0])
        source = self.root / "src.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((6, 5, 3), dtype=np.int16), affine), str(source))
        dest1 = self.root / "derived1"
        dest2 = self.root / "derived2"
        write_derived_dicom_series(source, dest1, format_name="nifti", modality="CT", case_id="case_x", study_id="study_x")
        write_derived_dicom_series(source, dest2, format_name="nifti", modality="CT", case_id="case_x", study_id="study_x")
        uids1 = {pydicom.dcmread(p, stop_before_pixels=True).StudyInstanceUID for p in dest1.glob("*.dcm")}
        uids2 = {pydicom.dcmread(p, stop_before_pixels=True).StudyInstanceUID for p in dest2.glob("*.dcm")}
        self.assertEqual(uids1, uids2)
        self.assertEqual(1, len(uids1))

    def test_registry_put_allow_update_rejects_identity_field_change(self) -> None:
        registry = FileRegistry(self.root / "registry_immutable")
        base_image = {
            "schema_version": "image_artifact.v1",
            "image_id": "img_imm",
            "case_id": "case_imm",
            "modality": "CT",
            "format": "dicom_series",
            "path": str(self.root / "img"),
            "hash": "sha256:" + "0" * 64,
            "hash_scope": "bundle_manifest",
            "pixel_type": "int16",
            "shape": [2, 2, 2],
            "spacing": [1.0, 1.0, 1.0],
            "origin": [0.0, 0.0, 0.0],
            "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "geometry_status": "complete",
            "geometry_evidence": {
                "coordinate_system": "LPS",
                "shape": "header",
                "spacing": "header",
                "origin": "header",
                "direction": "header",
                "assumptions": [],
            },
            "source": {"type": "test", "import_batch": "test", "reader": {"name": "test", "version": "1"}},
            "usability": {"annotation": "allowed", "training": "allowed", "evaluation": "allowed", "reasons": []},
        }
        registry.put("images", base_image)
        moved = {**base_image, "case_id": "case_other"}
        with self.assertRaisesRegex(ValidationError, "immutable field 'case_id'"):
            registry.put("images", moved, allow_update=True)
        refreshed = {**base_image, "modality": "MR"}
        registry.put("images", refreshed, allow_update=True)
        self.assertEqual("MR", registry.get("images", "img_imm")["modality"])


if __name__ == "__main__":
    unittest.main()
