# -*- coding: utf-8 -*-
"""P06: export exactly one managed Mask selected by review, target, and organ."""

from __future__ import print_function

import os
import sys

import mimics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "runtime_py35"))
from sp_common import export_mask_u8, find_mask, write_error_report, write_json  # noqa: E402


def main():
    if len(sys.argv) < 6:
        raise RuntimeError("usage: p06_selective_export.py REVIEW_ID TARGET_ID ORGAN OUTPUT_U8 OUTPUT_JSON")
    review_id, target_id, organ = sys.argv[1:4]
    mask = find_mask(mimics, review_id, target_id, organ)
    if mask is None:
        raise RuntimeError("managed Mask not found")
    exported = export_mask_u8(mask, os.path.abspath(sys.argv[4]))
    exported.update({"review_id": review_id, "target_id": target_id, "organ": organ})
    write_json(
        os.path.abspath(sys.argv[5]),
        {
            "schema_version": "mimics_probe_p06.v1",
            "mimics_version": str(mimics.get_version()),
            "export": exported,
            "status": "passed",
        },
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        output = os.path.abspath(sys.argv[5]) if len(sys.argv) > 5 else os.path.abspath("p06_error.json")
        write_error_report(output + ".error.json", "p06_selective_export", error)
        raise

