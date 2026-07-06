# -*- coding: utf-8 -*-
"""Save all managed Masks as a portable recovery checkpoint."""

from __future__ import print_function

import os
import shutil
import sys
import time

import mimics

from sp_common import (
    buffer_mapping_evidence_for_image,
    expected_mimics_shape,
    export_mask_u8_gzip,
    find_mask,
    load_json,
    managed_masks,
    match_images,
    metadata_get,
    write_error_report,
    write_json,
)

DEFAULT_CHECKPOINT_KEEP_COUNT = 3


def discover_runtime():
    masks = managed_masks(mimics)
    if not masks:
        raise RuntimeError("No SegmentationPlatform managed Masks were found")
    review_ids = set(metadata_get(mask, "sp.review_id", "") for mask in masks)
    package_roots = set(metadata_get(mask, "sp.package_root", "") for mask in masks)
    if len(review_ids) != 1 or "" in review_ids:
        raise RuntimeError("The project contains zero or multiple review_id values")
    if len(package_roots) != 1 or "" in package_roots:
        raise RuntimeError("The project contains zero or multiple package roots")
    package_root = list(package_roots)[0]
    return load_json(os.path.join(package_root, "working", "mimics_runtime.json"))


def cleanup_old_checkpoints(runtime, keep_count):
    try:
        keep_count = int(keep_count)
    except Exception:
        keep_count = DEFAULT_CHECKPOINT_KEEP_COUNT
    if keep_count < 1:
        keep_count = 1
    checkpoints_root = os.path.join(
        runtime["package_root"],
        "working",
        "checkpoints",
        runtime["review_id"],
    )
    if not os.path.isdir(checkpoints_root):
        return []
    candidates = []
    for name in os.listdir(checkpoints_root):
        path = os.path.join(checkpoints_root, name)
        if name == "latest.json" or not os.path.isdir(path):
            continue
        manifest = os.path.join(path, "checkpoint_manifest.json")
        if os.path.isfile(manifest):
            candidates.append((name, path))
    candidates.sort(reverse=True)
    removed = []
    for _name, path in candidates[keep_count:]:
        shutil.rmtree(path)
        removed.append(path)
    return removed


def main(keep_count=None):
    runtime = discover_runtime()
    if keep_count is None:
        keep_count = os.environ.get("SP_CHECKPOINT_KEEP_COUNT", DEFAULT_CHECKPOINT_KEEP_COUNT)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_{0}".format(os.getpid())
    checkpoint_root = os.path.join(
        runtime["package_root"],
        "working",
        "checkpoints",
        runtime["review_id"],
        timestamp,
    )
    entries = []
    base_labels = {}
    evidence_by_image_id = {}
    image_map = match_images(mimics, runtime["image_sets"])
    for target in runtime["targets"]:
        evidence_by_image_id[target["image_id"]] = buffer_mapping_evidence_for_image(runtime, target["image_id"])
        base_labels[target["target_id"]] = {
            "label_id": target.get("base_label_id", ""),
            "sha256": target.get("base_label_sha256", ""),
        }
        for expected in target["masks"]:
            organ = expected["organ"]
            mask = find_mask(mimics, runtime["review_id"], target["target_id"], organ)
            if mask is None:
                raise RuntimeError("Missing Mask: {0}/{1}".format(target["target_id"], organ))
            if metadata_get(mask, "sp.image_id") != target["image_id"]:
                raise RuntimeError("Mask image_id mismatch: {0}/{1}".format(target["target_id"], organ))
            if metadata_get(mask, "sp.base_label_id", "") != target.get("base_label_id", ""):
                raise RuntimeError("Mask base_label_id mismatch: {0}/{1}".format(target["target_id"], organ))
            if metadata_get(mask, "sp.base_label_hash", "") != target.get("base_label_sha256", ""):
                raise RuntimeError("Mask base_label_hash mismatch: {0}/{1}".format(target["target_id"], organ))
            if mask.image != image_map[target["image_id"]]:
                raise RuntimeError("Mask image set mismatch: {0}/{1}".format(target["target_id"], organ))
            actual_shape = [int(value) for value in mask.get_voxel_buffer().shape]
            expected_shape = expected_mimics_shape(runtime, target["image_id"])
            if actual_shape != expected_shape:
                raise RuntimeError(
                    "Mask shape mismatch: {0}/{1}: {2} != {3}".format(
                        target["target_id"], organ, actual_shape, expected_shape
                    )
                )
            output_path = os.path.join(
                checkpoint_root,
                "buffers",
                target["image_id"],
                target["target_id"],
                organ + ".u8.gz",
            )
            exported = export_mask_u8_gzip(mask, output_path)
            exported.update(
                {
                    "path": os.path.relpath(output_path, runtime["package_root"]).replace("\\", "/"),
                    "path_base": "package_root",
                    "target_id": target["target_id"],
                    "image_id": target["image_id"],
                    "organ": organ,
                }
            )
            entries.append(exported)

    checkpoint_manifest = os.path.join(checkpoint_root, "checkpoint_manifest.json")
    write_json(
        checkpoint_manifest,
        {
            "schema_version": "mimics_checkpoint.v1",
            "review_id": runtime["review_id"],
            "package_id": runtime["package_id"],
            "created_at": timestamp,
            "mimics_version": str(mimics.get_version()),
            "python_version": sys.version,
            "buffer_mapping_evidence_id": runtime.get("buffer_mapping", {}).get("evidence_id", ""),
            "buffer_mapping_evidence_by_image_id": evidence_by_image_id,
            "base_labels": base_labels,
            "entries": entries,
        },
    )
    latest_path = os.path.join(
        runtime["package_root"],
        "working",
        "checkpoints",
        runtime["review_id"],
        "latest.json",
    )
    write_json(
        latest_path,
        {
            "schema_version": "mimics_checkpoint_pointer.v1",
            "review_id": runtime["review_id"],
            "checkpoint_manifest": os.path.relpath(
                checkpoint_manifest, runtime["package_root"]
            ).replace("\\", "/"),
        },
    )
    removed_checkpoints = cleanup_old_checkpoints(runtime, keep_count)
    mimics.file.save_project(filename=runtime["mcs_path"], save_as_type="Mimics Project Files")
    mimics.dialogs.message_box(
        "Recovery backup saved.\n\n{0}\n\nKept latest {1}; removed {2} older backup(s).".format(
            checkpoint_manifest,
            keep_count,
            len(removed_checkpoints),
        ),
        title="Recovery Backup Saved",
        ui_blocking=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        try:
            runtime_value = discover_runtime()
            error_path = os.path.join(runtime_value["reports_dir"], "mimics_checkpoint_error.json")
        except Exception:
            error_path = os.path.abspath("mimics_checkpoint_error.json")
        write_error_report(error_path, "save_checkpoint", error)
        try:
            mimics.dialogs.message_box(
                "The checkpoint could not be saved. See mimics_checkpoint_error.json.\n\n{0}".format(str(error)),
                title="SegmentationPlatform - Checkpoint Failed",
                ui_blocking=True,
            )
        finally:
            raise
