# -*- coding: utf-8 -*-
"""P05: record voxel-center world coordinates needed to solve the buffer mapping."""

from __future__ import print_function

import os
import sys

import mimics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime_py35"))
from sp_common import image_identity, write_error_report, write_json  # noqa: E402


def main():
    if len(sys.argv) < 2:
        raise RuntimeError("usage: p05_geometry_roundtrip.py OUTPUT_JSON")
    image = mimics.data.images.get_active()
    if image is None:
        raise RuntimeError("no active image set")
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
    write_json(
        os.path.abspath(sys.argv[1]),
        {
            "schema_version": "mimics_probe_p05.v1",
            "mimics_version": str(mimics.get_version()),
            "image": image_identity(image),
            "voxel_centers": coordinates,
            "status": "evidence_collected",
            "decision": "manual comparison with the platform affine is still required",
        },
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        output = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.abspath("p05_error.json")
        write_error_report(output + ".error.json", "p05_geometry_roundtrip", error)
        raise

