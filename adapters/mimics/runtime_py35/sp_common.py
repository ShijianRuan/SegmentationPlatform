# -*- coding: utf-8 -*-
"""Shared Mimics 21 helpers. This file must remain compatible with Python 3.5."""

from __future__ import print_function

import hashlib
import gzip
import json
import os
import sys
import tempfile
import traceback


METADATA_KEYS = (
    "sp.review_id",
    "sp.target_id",
    "sp.image_id",
    "sp.organ",
    "sp.base_label_id",
    "sp.base_label_hash",
    "sp.package_root",
)

TOGGLE_PREFIX_SELECTED = "[x] "
TOGGLE_PREFIX_CLEAR = "[ ] "


def load_json(path):
    with open(path, "r") as handle:
        return json.load(handle)


def write_json(path, value):
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    fd, temporary = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=directory or None)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
        if os.path.exists(path):
            os.remove(path)
        os.rename(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def sha256_bytes(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def metadata_get(obj, name, default=None):
    try:
        item = obj.metadata.find(name)
        return item.value if item is not None else default
    except Exception:
        try:
            return obj.metadata[name].value
        except Exception:
            return default


def metadata_get_required(obj, name):
    marker = object()
    value = metadata_get(obj, name, marker)
    if value is marker:
        raise RuntimeError("metadata value could not be read: {0}".format(name))
    return value


def metadata_set(obj, name, value):
    text = "" if value is None else str(value)
    item = None
    try:
        item = obj.metadata.find(name)
    except Exception:
        pass
    if item is None:
        obj.metadata.create(name=name, value=text)
    else:
        item.value = text


def mask_metadata(mask):
    return dict((key, metadata_get(mask, key, "")) for key in METADATA_KEYS)


def managed_masks(mimics, review_id=None):
    result = []
    for mask in mimics.data.masks:
        current_review = metadata_get(mask, "sp.review_id", "")
        if not current_review:
            continue
        if review_id is None or current_review == review_id:
            result.append(mask)
    return result


def find_mask(mimics, review_id, target_id, organ):
    matches = []
    for mask in managed_masks(mimics, review_id):
        if metadata_get(mask, "sp.target_id") == target_id and metadata_get(mask, "sp.organ") == organ:
            matches.append(mask)
    if len(matches) > 1:
        raise RuntimeError("duplicate managed Mask for {0}/{1}".format(target_id, organ))
    return matches[0] if matches else None


def dicom_tag_value(image, group, element):
    try:
        tag = image.get_dicom_tags().get((group, element))
        return "" if tag is None else str(tag.value)
    except Exception:
        return ""


def image_identity(image):
    dimensions = [int(value) for value in image.logical_dimensions]
    uid = dicom_tag_value(image, 0x0020, 0x000E)
    description = dicom_tag_value(image, 0x0008, 0x103E)
    return {
        "logical_dimensions": dimensions,
        "dicom_series_uid_sha256": sha256_bytes(uid.encode("utf-8")) if uid else None,
        "series_description": description,
    }


def match_images(mimics, expected_images):
    available = []
    for image in mimics.data.images:
        available.append((image, image_identity(image)))
    result = {}
    used = set()
    for expected in expected_images:
        matches = []
        uid_shape_mismatches = []
        expected_uid = expected.get("dicom_series_uid_sha256")
        for image, identity in available:
            if id(image) in used:
                continue
            if expected_uid and identity.get("dicom_series_uid_sha256") == expected_uid:
                if identity["logical_dimensions"] == expected["platform_shape"]:
                    matches.append((image, identity))
                else:
                    uid_shape_mismatches.append(identity["logical_dimensions"])
                continue
            if not expected_uid and identity["logical_dimensions"] == expected["platform_shape"]:
                expected_description = expected.get("series_description", "")
                if not expected_description or expected_description == identity.get("series_description", ""):
                    matches.append((image, identity))
        if len(matches) != 1:
            if expected_uid and uid_shape_mismatches:
                raise RuntimeError(
                    "image_id {0} matched the expected Series UID but shape differs; expected shape={1}, found shapes={2}".format(
                        expected["image_id"], expected["platform_shape"], uid_shape_mismatches
                    )
                )
            raise RuntimeError(
                "image_id {0} matched {1} Mimics image sets; expected UID={2}, shape={3}".format(
                    expected["image_id"], len(matches), expected_uid, expected["platform_shape"]
                )
            )
        image, identity = matches[0]
        result[expected["image_id"]] = image
        used.add(id(image))
    return result


def expected_mimics_shape(runtime, image_id):
    image = next(item for item in runtime["image_sets"] if item["image_id"] == image_id)
    mapping = runtime.get("buffer_mapping_by_image_id", {}).get(image_id, runtime.get("buffer_mapping", {}))
    axes = mapping.get("platform_to_mimics_axes", [0, 1, 2])
    return [int(image["platform_shape"][int(axis)]) for axis in axes]


def buffer_mapping_evidence_for_image(runtime, image_id):
    mapping = runtime.get("buffer_mapping_by_image_id", {}).get(image_id, runtime.get("buffer_mapping", {}))
    return mapping.get("evidence_id", "")


def apply_predefined_answers(mimics, answers):
    for dialog_id, answer in answers.items():
        mimics.dialogs.set_predefined_answer(str(dialog_id), str(answer))


def set_mask_buffer_from_u8(mask, path, shape):
    if path.lower().endswith(".gz"):
        with gzip.open(path, "rb") as handle:
            raw = handle.read()
    else:
        raw = open(path, "rb").read()
    expected = int(shape[0]) * int(shape[1]) * int(shape[2])
    if len(raw) != expected:
        raise RuntimeError("buffer byte count mismatch: {0} != {1}".format(len(raw), expected))
    try:
        import numpy as np

        pixels = np.frombuffer(raw, dtype=np.uint8).reshape(tuple(shape)).astype(np.bool_)
        mask.set_voxel_buffer(pixels)
        return "numpy"
    except ImportError:
        view = memoryview(bytearray(raw)).cast("?", shape=list(shape))
        mask.set_voxel_buffer(view)
        return "memoryview"


def export_mask_u8(mask, path):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    view = mask.get_voxel_buffer()
    raw = view.tobytes()
    with open(path, "wb") as handle:
        handle.write(raw)
    return {
        "path": os.path.abspath(path),
        "sha256": sha256_file(path),
        "byte_count": len(raw),
        "mimics_shape": [int(value) for value in view.shape],
        "number_of_pixels": int(mask.number_of_pixels),
    }


def export_mask_u8_gzip(mask, path):
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        os.makedirs(directory)
    view = mask.get_voxel_buffer()
    raw = view.tobytes()
    with gzip.open(path, "wb", compresslevel=6) as handle:
        handle.write(raw)
    return {
        "path": os.path.abspath(path),
        "sha256": sha256_file(path),
        "byte_count": os.path.getsize(path),
        "uncompressed_byte_count": len(raw),
        "mimics_shape": [int(value) for value in view.shape],
        "number_of_pixels": int(mask.number_of_pixels),
        "compression": "gzip",
    }


def write_error_report(path, stage, error):
    write_json(
        path,
        {
            "schema_version": "mimics_runtime_error.v1",
            "stage": stage,
            "python_version": sys.version,
            "error_type": error.__class__.__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        },
    )
