# -*- coding: utf-8 -*-
"""P04: write asymmetric corner voxels to a Mask and export the raw buffer."""

from __future__ import print_function

import os
import sys

import mimics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime_py35"))
from sp_common import export_mask_u8, write_error_report, write_json  # noqa: E402


def main():
    if len(sys.argv) < 3:
        raise RuntimeError("usage: p04_mask_buffer.py OUTPUT_U8 OUTPUT_JSON")
    image = mimics.data.images.get_active()
    if image is None:
        raise RuntimeError("no active image set")
    mask = mimics.segment.create_mask()
    mask.name = "SP_P04_ASYMMETRIC_BUFFER"
    view = mask.get_voxel_buffer()
    points = [
        (0, 0, 0),
        (1, 2, 3),
        (int(view.shape[0]) - 1, int(view.shape[1]) - 2, int(view.shape[2]) - 3),
    ]
    for point in points:
        if all(point[axis] >= 0 and point[axis] < int(view.shape[axis]) for axis in range(3)):
            view[point] = True
    mask.set_voxel_buffer(view)
    exported = export_mask_u8(mask, os.path.abspath(sys.argv[1]))
    write_json(
        os.path.abspath(sys.argv[2]),
        {
            "schema_version": "mimics_probe_p04.v1",
            "mimics_version": str(mimics.get_version()),
            "logical_dimensions": [int(value) for value in image.logical_dimensions],
            "points": [list(point) for point in points],
            "export": exported,
            "status": "passed",
        },
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        output = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.abspath("p04_error.json")
        write_error_report(output + ".error.json", "p04_mask_buffer", error)
        raise

