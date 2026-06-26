from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from segplatform.adapters.mimics.doctor import load_workstation_config
from segplatform.adapters.mimics.prepare import prepare_case
from segplatform.common import load_data, utc_now
from segplatform.errors import ConfigurationError
from segplatform.registry import FileRegistry


def _mimics_runtime_command(
    case_root: Path,
    workstation_config_path: Path,
    *,
    script_name: str,
    log_name: str,
    background: bool = False,
    extra_args: list[str] | None = None,
) -> list[str]:
    config = load_workstation_config(workstation_config_path)
    runtime_path = case_root.resolve() / "working" / "mimics_runtime.json"
    if not runtime_path.is_file():
        raise ConfigurationError(f"run `sp mimics prepare` first; missing {runtime_path}")
    executable = Path(os.path.expandvars(str(config["executable"]))).expanduser()
    script = Path(os.path.expandvars(str(config["runtime_script_dir"]))).expanduser() / script_name
    log_path = case_root.resolve() / "reports" / log_name
    if not executable.is_file():
        raise ConfigurationError(f"Mimics executable not found: {executable}")
    if not script.is_file():
        raise ConfigurationError(f"Mimics runtime script not found: {script}")
    command = [str(executable)]
    if background:
        command.append("-background_mode")
    command.extend(["-save_log", str(log_path), "-run_script", str(script), str(runtime_path)])
    command.extend(extra_args or [])
    return command


def build_open_command(case_root: Path, workstation_config_path: Path) -> list[str]:
    return _mimics_runtime_command(
        case_root,
        workstation_config_path,
        script_name="sp_open_review.py",
        log_name="mimics_open.log",
    )


def build_prebuild_command(case_root: Path, workstation_config_path: Path) -> list[str]:
    return _mimics_runtime_command(
        case_root,
        workstation_config_path,
        script_name="sp_open_review.py",
        log_name="mimics_prebuild.log",
        background=True,
        extra_args=["--background-prebuild"],
    )


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


def prebuild_workspace(
    case_root: Path,
    workstation_config_path: Path,
    *,
    rebuild_workspace: bool = False,
    dry_run: bool = False,
    wait: bool = True,
) -> dict[str, Any]:
    runtime_path = prepare_case(case_root, workstation_config_path, rebuild_workspace=rebuild_workspace)
    runtime = load_data(runtime_path)
    result: dict[str, Any] = {
        "runtime_manifest": str(runtime_path),
        "mcs_path": runtime["mcs_path"],
        "prebuilt_marker_path": runtime.get("prebuilt_marker_path"),
        "runtime_mode": runtime.get("mode"),
        "started": False,
    }
    if not rebuild_workspace and runtime.get("mode") == "prebuilt":
        result["status"] = "already_prebuilt"
        return result
    if not rebuild_workspace and runtime.get("mode") == "resume":
        result["status"] = "already_exists"
        result["reason"] = "existing .mcs has no prebuild marker; use --rebuild-workspace to replace it"
        return result

    command = build_prebuild_command(case_root, workstation_config_path)
    result["command"] = command
    if dry_run:
        return result
    process = subprocess.Popen(command)
    result.update({"started": True, "pid": process.pid})
    if wait:
        returncode = process.wait()
        result["returncode"] = returncode
        result["status"] = "prebuilt" if returncode == 0 and Path(runtime["mcs_path"]).is_file() else "failed"
    return result
