# -*- coding: utf-8 -*-
"""Mimics Scripting Library entry point for daily annotation work.

The file name is intentionally user-facing: Mimics registers scripts in this
folder directly in Script -> Scripting Library.
"""

from __future__ import print_function

import os
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "runtime_py35"))
LOCAL_CONFIG = os.path.join(SCRIPT_DIR, "sp_review_console.local.json")

if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

if "SP_REVIEW_CONSOLE_CONFIG" not in os.environ and os.path.isfile(LOCAL_CONFIG):
    os.environ["SP_REVIEW_CONSOLE_CONFIG"] = LOCAL_CONFIG

import sp_review_console


if __name__ == "__main__":
    sys.exit(sp_review_console.main())
