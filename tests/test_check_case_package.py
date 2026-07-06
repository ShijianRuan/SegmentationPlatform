from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_case_package import validate_case_package


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CasePackageV05Tests(unittest.TestCase):
    def make_package(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        dataset_root = Path(temporary.name) / "dataset_package"
        case_root = dataset_root / "cases" / "case_001"
        config_root = dataset_root / "config"
        image_root = case_root / "images" / "img_ct"
        config_root.mkdir(parents=True)
        image_root.mkdir(parents=True)

        anatomy = config_root / "anatomy_vocabulary.yaml"
        review_map = config_root / "review_label_map.yaml"
        image = image_root / "image.nii.gz"
        anatomy.write_text("organs: [liver, kidney_left]\n", encoding="utf-8")
        review_map.write_text("labels: {liver: 1, kidney_left: 2}\n", encoding="utf-8")
        image.write_bytes(b"image")

        manifest = {
            "schema_version": "case_package.v0.5",
            "package_id": "pkg_case_001",
            "case_id": "case_001",
            "leakage_group_id": "subject_001",
            "study_id": "study_001",
            "data_governance": {
                "deidentification_status": "verified",
                "profile": "test_profile",
                "profile_version": "1",
            },
            "created_at": "2026-06-13T10:00:00+08:00",
            "config_ref": "../../config",
            "config_sha256": {
                "anatomy_vocabulary.yaml": sha256(anatomy),
                "review_label_map.yaml": sha256(review_map),
            },
            "image_sets": [
                {
                    "image_id": "img_ct",
                    "modality": "CT",
                    "image_path": "images/img_ct/image.nii.gz",
                    "sha256": sha256(image),
                    "shape": [32, 32, 16],
                    "spacing": [1.0, 1.0, 2.0],
                    "origin": [0.0, 0.0, 0.0],
                    "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                    "coordinate_system": "RAS",
                }
            ],
            "review": {
                "review_id": "review_001",
                "tool": "mimics",
                "status": "ready",
                "assignee": "annotator_01",
                "targets": [
                    {
                        "target_id": "target_abdomen",
                        "image_id": "img_ct",
                        "organs": ["liver", "kidney_left"],
                        "base_label_id": "label_v1",
                        "base_label_sha256": "sha256:" + ("a" * 64),
                    }
                ],
            },
        }
        (case_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return case_root

    def finding_codes(self, package: Path) -> set[str]:
        report = validate_case_package(package)
        return {finding["code"] for finding in report["findings"]}

    def test_minimal_image_only_package_passes(self) -> None:
        package = self.make_package()
        report = validate_case_package(package)
        self.assertEqual("passed", report["status"], report["findings"])

    def test_legacy_flat_label_layout_is_rejected(self) -> None:
        package = self.make_package()
        labels = package / "labels"
        labels.mkdir()
        (labels / "draft_label.nii.gz").write_bytes(b"label")
        self.assertIn("legacy_label_layout", self.finding_codes(package))

    def test_label_directory_must_reference_an_image_set(self) -> None:
        package = self.make_package()
        unknown = package / "labels" / "img_unknown"
        unknown.mkdir(parents=True)
        self.assertIn("label_image_unknown", self.finding_codes(package))

    def test_image_path_must_match_image_id_directory(self) -> None:
        package = self.make_package()
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["image_sets"][0]["image_path"] = "images/img_other/image.nii.gz"
        (package / "images" / "img_other").mkdir()
        (package / "images" / "img_other" / "image.nii.gz").write_bytes(b"image")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self.assertIn("manifest_image_layout_mismatch", self.finding_codes(package))

    def test_target_organs_must_be_unique(self) -> None:
        package = self.make_package()
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["review"]["targets"][0]["organs"].append("liver")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        self.assertIn("manifest_target_organs_duplicate", self.finding_codes(package))

    def test_multiple_image_sets_with_scoped_labels_pass(self) -> None:
        package = self.make_package()
        second_image = package / "images" / "img_mr" / "image.nii.gz"
        second_image.parent.mkdir(parents=True)
        second_image.write_bytes(b"second-image")

        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["image_sets"].append(
            {
                "image_id": "img_mr",
                "modality": "MR",
                "image_path": "images/img_mr/image.nii.gz",
                "sha256": sha256(second_image),
                "shape": [24, 24, 12],
                "spacing": [1.2, 1.2, 2.5],
                "origin": [0.0, 0.0, 0.0],
                "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
                "coordinate_system": "RAS",
            }
        )
        manifest["review"]["targets"].append(
            {
                "target_id": "target_mr_liver",
                "image_id": "img_mr",
                "organs": ["liver"],
            }
        )
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        (package / "labels" / "img_ct" / "masks").mkdir(parents=True)
        (package / "labels" / "img_ct" / "masks" / "liver.nii.gz").write_bytes(b"mask")
        (package / "labels" / "img_mr").mkdir(parents=True)
        (package / "labels" / "img_mr" / "draft_label.nii.gz").write_bytes(b"label")

        report = validate_case_package(package)
        self.assertEqual("passed", report["status"], report["findings"])

    def test_completed_submission_requires_every_target_organ(self) -> None:
        package = self.make_package()
        submission = package / "submissions" / "review_001"
        submission.mkdir(parents=True)
        (submission / "submission_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "review_submission.v1",
                    "review_id": "review_001",
                    "target_ids": ["target_abdomen"],
                    "action": "submit_complete",
                    "assignee": "annotator_01",
                    "base_labels": {
                        "target_abdomen": {
                            "label_id": "label_v1",
                            "sha256": "sha256:" + ("a" * 64),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (submission / "buffers" / "img_ct" / "target_abdomen").mkdir(parents=True)
        (submission / "buffers" / "img_ct" / "target_abdomen" / "liver.u8").write_bytes(b"mask")
        (package / "reports").mkdir()
        (package / "reports" / "review_report.json").write_text("{}", encoding="utf-8")
        (package / "provenance").mkdir()
        (package / "provenance" / "tool_export.json").write_text("{}", encoding="utf-8")

        codes = self.finding_codes(package)
        self.assertIn("submission_output_missing", codes)

    def test_complete_submission_with_buffers_passes(self) -> None:
        package = self.make_package()
        submission = package / "submissions" / "review_001"
        buffers = submission / "buffers" / "img_ct" / "target_abdomen"
        buffers.mkdir(parents=True)
        for organ in ("liver", "kidney_left"):
            (buffers / f"{organ}.u8").write_bytes(b"mask")
        (submission / "submission_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "review_submission.v1",
                    "review_id": "review_001",
                    "target_ids": ["target_abdomen"],
                    "action": "submit_complete",
                    "assignee": "annotator_01",
                    "base_labels": {
                        "target_abdomen": {
                            "label_id": "label_v1",
                            "sha256": "sha256:" + ("a" * 64),
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (package / "reports").mkdir()
        (package / "reports" / "review_report.json").write_text("{}", encoding="utf-8")
        (package / "provenance").mkdir()
        (package / "provenance" / "tool_export.json").write_text("{}", encoding="utf-8")

        report = validate_case_package(package)
        self.assertEqual("passed", report["status"], report["findings"])


if __name__ == "__main__":
    unittest.main()
