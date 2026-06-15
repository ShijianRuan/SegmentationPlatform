# -*- coding: utf-8 -*-
"""Write Mimics 21 scripting capability diagnostics to the JSON path in argv[1]."""

from __future__ import print_function

import os
import platform
import sys

import mimics

from sp_common import write_error_report, write_json


def has(path):
    value = mimics
    for part in path.split("."):
        if not hasattr(value, part):
            return False
        value = getattr(value, part)
    return True


def main():
    if len(sys.argv) < 2:
        raise RuntimeError("usage: sp_diagnostics.py OUTPUT_JSON")
    output = os.path.abspath(sys.argv[1])
    report = {
        "schema_version": "mimics_diagnostics.v1",
        "mimics_version": str(mimics.get_version()),
        "python_version": sys.version,
        "platform": platform.platform(),
        "api": {},
    }
    paths = [
        "file.import_dicom_images",
        "file.close_project",
        "file.open_project",
        "file.save_project",
        "data.images.get_active",
        "data.images.set_active",
        "segment.create_mask",
        "dialogs.message_box",
        "dialogs.question_box",
        "dialogs.set_predefined_answer",
    ]
    for path in paths:
        report["api"][path] = has(path)
    try:
        import numpy

        report["numpy"] = {"available": True, "version": numpy.__version__}
    except Exception as error:
        report["numpy"] = {"available": False, "error": str(error)}
    report["status"] = "passed" if all(report["api"].values()) else "failed"
    write_json(output, report)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        output_path = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath("mimics_diagnostics_error.json")
        write_error_report(output_path + ".error.json", "diagnostics", error)
        raise
