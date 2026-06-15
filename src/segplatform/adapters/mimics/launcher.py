from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from segplatform.adapters.mimics.doctor import load_workstation_config
from segplatform.common import load_data, utc_now
from segplatform.errors import ConfigurationError
from segplatform.registry import FileRegistry


def build_open_command(case_root: Path, workstation_config_path: Path) -> list[str]:
    config = load_workstation_config(workstation_config_path)
    runtime_path = case_root.resolve() / "working" / "mimics_runtime.json"
    if not runtime_path.is_file():
        raise ConfigurationError(f"run `sp mimics prepare` first; missing {runtime_path}")
    executable = Path(os.path.expandvars(str(config["executable"]))).expanduser()
    script = Path(os.path.expandvars(str(config["runtime_script_dir"]))).expanduser() / "sp_open_review.py"
    log_path = case_root.resolve() / "reports" / "mimics_open.log"
    if not executable.is_file():
        raise ConfigurationError(f"Mimics executable not found: {executable}")
    if not script.is_file():
        raise ConfigurationError(f"Mimics runtime script not found: {script}")
    return [
        str(executable),
        "-save_log",
        str(log_path),
        "-run_script",
        str(script),
        str(runtime_path),
    ]


def open_case(
    case_root: Path,
    workstation_config_path: Path,
    *,
    dry_run: bool = False,
    wait: bool = False,
    registry_root: Path | None = None,
) -> dict[str, Any]:
    command = build_open_command(case_root, workstation_config_path)
    if dry_run:
        return {"command": command, "started": False}
    process = subprocess.Popen(command)
    result = {"command": command, "started": True, "pid": process.pid}
    if registry_root:
        runtime = load_data(case_root.resolve() / "working" / "mimics_runtime.json")
        registry = FileRegistry(registry_root)
        review = registry.get("reviews", runtime["review_id"])
        review["status"] = "in_progress"
        for target in review["targets"]:
            if target["status"] == "ready":
                target["status"] = "in_progress"
        review.setdefault("events", []).append(
            {
                "at": utc_now(),
                "action": "open_started",
                "actor": runtime.get("assignee") or "offline_operator",
                "target_ids": [target["target_id"] for target in review["targets"]],
            }
        )
        registry.put("reviews", review, allow_update=True)
    if wait:
        result["returncode"] = process.wait()
    return result
