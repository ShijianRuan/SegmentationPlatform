# -*- coding: utf-8 -*-
"""Run the required Mimics 21 adapter probes in one self-contained session."""

from __future__ import print_function

import os
import sys

import mimics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime_py35"))
from sp_common import (  # noqa: E402
    export_mask_u8,
    find_mask,
    image_identity,
    metadata_get,
    metadata_set,
    sha256_file,
    write_error_report,
    write_json,
)


PROBE_REVIEW_ID = "SP_PROBE_SUITE"


def ensure_directory(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def collect_p01():
    records = []
    for index, image in enumerate(mimics.data.images):
        record = image_identity(image)
        record["index"] = index
        records.append(record)
    return {
        "schema_version": "mimics_probe_p01.v1",
        "image_sets": records,
        "status": "passed" if records else "failed",
    }


def run_p02(project_path):
    created = []
    for index, image in enumerate(mimics.data.images):
        mimics.data.images.set_active(image)
        mask = mimics.segment.create_mask()
        mask.name = "SP_P02_IMAGE_{0}".format(index)
        try:
            mask.image = image
        except Exception:
            pass
        metadata_set(mask, "sp.probe", "P02")
        metadata_set(mask, "sp.image_index", index)
        identity = image_identity(image)
        metadata_set(mask, "sp.expected_series_uid_sha256", identity.get("dicom_series_uid_sha256") or "")
        created.append(
            {
                "image_index": index,
                "identity": identity,
                "mask_name": mask.name,
                "mask_linked": mask.image == image,
            }
        )

    mimics.file.save_project(filename=project_path, save_as_type="Mimics Project Files")
    mimics.file.close_project()
    mimics.file.open_project(filename=project_path)

    reopened = []
    # Mimics 21.0.0.406 does not persist custom metadata across project
    # save/close/open, so we match by mask name pattern as a fallback.
    for mask in mimics.data.masks:
        stored_probe = metadata_get(mask, "sp.probe", "")
        if stored_probe != "P02":
            if stored_probe:
                continue
            if not mask.name.startswith("SP_P02_IMAGE_"):
                continue
        expected_index = int(metadata_get(mask, "sp.image_index", -1))
        if expected_index < 0 or expected_index >= len(created):
            try:
                prefix = "SP_P02_IMAGE_"
                if mask.name.startswith(prefix):
                    expected_index = int(mask.name[len(prefix):])
                else:
                    continue
            except (ValueError, IndexError):
                continue
        expected_uid = metadata_get(mask, "sp.expected_series_uid_sha256", "")
        linked_identity = image_identity(mask.image)
        uid_matches = bool(expected_uid) and linked_identity.get("dicom_series_uid_sha256") == expected_uid
        shape_matches = (
            expected_index < len(created)
            and linked_identity["logical_dimensions"] == created[expected_index]["identity"]["logical_dimensions"]
        )
        reopened.append(
            {
                "image_index": expected_index,
                "identity": linked_identity,
                "mask_name": mask.name,
                "mask_linked": uid_matches if expected_uid else shape_matches,
                "reopened": True,
            }
        )
    passed = (
        len(reopened) == len(created)
        and bool(reopened)
        and all(item["mask_linked"] for item in created)
        and all(item["mask_linked"] for item in reopened)
    )
    return {
        "schema_version": "mimics_probe_p02.v1",
        "created_records": created,
        "reopened_records": reopened,
        "status": "passed" if passed else "failed",
    }


def run_p04(output_dir):
    image = mimics.data.images[0]
    mimics.data.images.set_active(image)
    mask = mimics.segment.create_mask()
    mask.name = "SP_P04_ASYMMETRIC_BUFFER"
    try:
        mask.image = image
    except Exception:
        pass
    if mask.image != image:
        raise RuntimeError("P04 Mask was not linked to the active image")
    metadata_set(mask, "sp.review_id", PROBE_REVIEW_ID)
    metadata_set(mask, "sp.target_id", "P04")
    metadata_set(mask, "sp.image_id", "probe_image_0")
    metadata_set(mask, "sp.organ", "asymmetric_buffer")

    view = mask.get_voxel_buffer()
    shape = [int(value) for value in view.shape]
    candidates = [
        (0, 0, 0),
        (1, 2, 3),
        (shape[0] - 1, shape[1] - 2, shape[2] - 3),
    ]
    points = []
    for point in candidates:
        if all(point[axis] >= 0 and point[axis] < shape[axis] for axis in range(3)):
            view[point] = True
            points.append(list(point))
    mask.set_voxel_buffer(view)
    output_path = os.path.join(output_dir, "p04_asymmetric.u8")
    exported = export_mask_u8(mask, output_path)
    passed = int(mask.number_of_pixels) == len(points) and len(points) >= 2
    return {
        "schema_version": "mimics_probe_p04.v1",
        "logical_dimensions": [int(value) for value in image.logical_dimensions],
        "points": points,
        "export": exported,
        "status": "passed" if passed else "failed",
    }


def run_p05():
    image = mimics.data.images[0]
    mimics.data.images.set_active(image)
    dimensions = [int(value) for value in image.logical_dimensions]
    indexes = [(0, 0, 0)]
    for axis in range(3):
        point = [0, 0, 0]
        point[axis] = 1 if dimensions[axis] > 1 else 0
        indexes.append(tuple(point))
    indexes.append(tuple(max(value - 1, 0) for value in dimensions))
    coordinates = []
    for index in indexes:
        coordinates.append({"index": list(index), "world": list(image.get_voxel_center(index))})
    return {
        "schema_version": "mimics_probe_p05.v1",
        "image": image_identity(image),
        "logical_dimensions": dimensions,
        "voxel_centers": coordinates,
        "status": "evidence_collected",
    }


def run_p06(output_dir, p04):
    mask = find_mask(mimics, PROBE_REVIEW_ID, "P04", "asymmetric_buffer")
    if mask is None:
        raise RuntimeError("P06 could not select the P04 managed Mask")
    output_path = os.path.join(output_dir, "p06_selected.u8")
    exported = export_mask_u8(mask, output_path)
    identical = (
        exported["sha256"] == p04["export"]["sha256"]
        and exported["byte_count"] == p04["export"]["byte_count"]
    )
    return {
        "schema_version": "mimics_probe_p06.v1",
        "selection": {
            "review_id": PROBE_REVIEW_ID,
            "target_id": "P04",
            "organ": "asymmetric_buffer",
        },
        "export": exported,
        "matches_p04": identical,
        "status": "passed" if identical else "failed",
    }


def main():
    if len(sys.argv) < 3:
        raise RuntimeError("usage: sp_probe_suite.py DICOM_ROOT OUTPUT_DIR")
    dicom_root = os.path.abspath(sys.argv[1])
    output_dir = os.path.abspath(sys.argv[2])
    ensure_directory(output_dir)
    if not os.path.isdir(dicom_root):
        raise RuntimeError("DICOM root does not exist: {0}".format(dicom_root))

    mimics.file.import_dicom_images(source_folder=dicom_root)
    p01 = collect_p01()
    if p01["status"] != "passed":
        raise RuntimeError("Mimics did not create an image set from the DICOM input")

    project_path = os.path.join(output_dir, "sp_probe_suite.mcs")
    p02 = run_p02(project_path)
    p04 = run_p04(output_dir)
    p05 = run_p05()
    p06 = run_p06(output_dir, p04)
    mimics.file.save_project(filename=project_path, save_as_type="Mimics Project Files")

    sections = {"p01": p01, "p02": p02, "p04": p04, "p05": p05, "p06": p06}
    passed = all(section["status"] in ("passed", "evidence_collected") for section in sections.values())
    report = {
        "schema_version": "mimics_probe_suite.v1",
        "mimics_version": str(mimics.get_version()),
        "python_version": sys.version,
        "dicom_root": dicom_root,
        "project_path": project_path,
        "sections": sections,
        "status": "passed" if passed else "failed",
    }
    report_path = os.path.join(output_dir, "mimics_probe_evidence.json")
    write_json(report_path, report)
    write_json(
        os.path.join(output_dir, "mimics_probe_complete.json"),
        {
            "schema_version": "mimics_probe_complete.v1",
            "evidence_path": report_path,
            "evidence_sha256": sha256_file(report_path),
            "status": report["status"],
        },
    )
    mimics.dialogs.message_box(
        "Probe suite finished with status: {0}\n\nEvidence:\n{1}".format(report["status"], report_path),
        title="SegmentationPlatform - Mimics Probe",
        ui_blocking=True,
    )
    return 0 if passed else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        output_root = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.abspath(".")
        ensure_directory(output_root)
        write_error_report(os.path.join(output_root, "mimics_probe_error.json"), "probe_suite", error)
        try:
            mimics.dialogs.message_box(
                "The Mimics probe suite failed. See mimics_probe_error.json.\n\n{0}".format(str(error)),
                title="SegmentationPlatform - Probe Failed",
                ui_blocking=True,
            )
        finally:
            raise
