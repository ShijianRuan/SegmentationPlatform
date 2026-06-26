# -*- coding: utf-8 -*-
"""Submit the selected targets in the current case as complete."""

from __future__ import print_function

import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for candidate in (
    os.path.join(SCRIPT_DIR, "runtime_py35"),
    os.path.join(SCRIPT_DIR, "..", "runtime_py35"),
):
    if os.path.isdir(candidate):
        sys.path.insert(0, os.path.abspath(candidate))
        break
os.environ["SP_WORKLIST_ROOT"] = SCRIPT_DIR

import sp_review_console


if __name__ == "__main__":
    sys.exit(sp_review_console.run_entry("submit_complete"))
