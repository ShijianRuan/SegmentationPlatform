# -*- coding: utf-8 -*-
"""P01: import a DICOM directory and record the resulting image sets."""

from __future__ import print_function

import os
import sys

import mimics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime_py35"))
from sp_common import image_identity, write_error_report, write_json  # noqa: E402


def main():
    if len(sys.argv) < 3:
        raise RuntimeError("usage: p01_dicom_grouping.py DICOM_ROOT OUTPUT_JSON")
    mimics.file.import_dicom_images(source_folder=os.path.abspath(sys.argv[1]))
    records = []
    for index, image in enumerate(mimics.data.images):
        identity = image_identity(image)
        identity["index"] = index
        records.append(identity)
    write_json(
        os.path.abspath(sys.argv[2]),
        {
            "schema_version": "mimics_probe_p01.v1",
            "mimics_version": str(mimics.get_version()),
            "image_sets": records,
            "status": "passed" if records else "failed",
        },
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        output = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else os.path.abspath("p01_error.json")
        write_error_report(output + ".error.json", "p01_dicom_grouping", error)
        raise

