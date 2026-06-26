# -*- coding: utf-8 -*-
"""P02: create one managed test Mask per image set and verify bindings after save."""

from __future__ import print_function

import os
import sys

import mimics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime_py35"))
from sp_common import image_identity, metadata_get, metadata_set, write_error_report, write_json  # noqa: E402


def main():
    if len(sys.argv) < 3:
        raise RuntimeError("usage: p02_image_set_binding.py OUTPUT_MCS OUTPUT_JSON")
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
        created.append(
            {
                "image_index": index,
                "identity": image_identity(image),
                "mask_name": mask.name,
                "mask_linked": mask.image == image,
            }
        )
    project_path = os.path.abspath(sys.argv[1])
    mimics.file.save_project(filename=project_path, save_as_type="Mimics Project Files")
    mimics.file.close_project()
    mimics.file.open_project(filename=project_path)
    records = []
    for mask in mimics.data.masks:
        if metadata_get(mask, "sp.probe") != "P02":
            continue
        expected_index = int(metadata_get(mask, "sp.image_index"))
        expected_image = mimics.data.images[expected_index]
        records.append(
            {
                "image_index": expected_index,
                "identity": image_identity(expected_image),
                "mask_name": mask.name,
                "mask_linked": mask.image == expected_image,
                "reopened": True,
            }
        )
    write_json(
        os.path.abspath(sys.argv[2]),
        {
            "schema_version": "mimics_probe_p02.v1",
            "mimics_version": str(mimics.get_version()),
            "created_records": created,
            "reopened_records": records,
            "status": "passed"
            if len(records) == len(created) and records and all(item["mask_linked"] for item in records)
            else "failed",
        },
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        output = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.abspath("p02_error.json")
        write_error_report(output + ".error.json", "p02_image_set_binding", error)
        raise
