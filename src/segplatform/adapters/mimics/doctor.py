from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Any

from segplatform.common import load_data, utc_now, write_json


def load_workstation_config(path: Path) -> dict[str, Any]:
    config = load_data(path)
    if config.get("schema_version") != "mimics_workstation.v1":
        raise ValueError("workstation config schema_version must be mimics_workstation.v1")
    return config


def doctor(config_path: Path, *, run_diagnostics: bool = False) -> dict[str, Any]:
    config = load_workstation_config(config_path)
    executable = Path(os.path.expandvars(str(config["executable"]))).expanduser()
    script_dir = Path(os.path.expandvars(str(config["runtime_script_dir"]))).expanduser()
    work_root = Path(os.path.expandvars(str(config["work_root"]))).expanduser()
    checks = []

    def add(code: str, passed: bool, detail: str) -> None:
        checks.append({"code": code, "passed": passed, "detail": detail})

    add("host_os", platform.system() == "Windows", f"detected {platform.system()}")
    add("edition_recorded", bool(config.get("edition")), str(config.get("edition", "")))
    add(
        "scripting_license_recorded",
        "Scripting" in set(str(item) for item in config.get("license_modules", [])),
        ", ".join(str(item) for item in config.get("license_modules", [])),
    )
    add("executable", executable.is_file(), str(executable))
    add("runtime_script_dir", script_dir.is_dir(), str(script_dir))
    add("diagnostics_script", (script_dir / "sp_diagnostics.py").is_file(), str(script_dir / "sp_diagnostics.py"))
    try:
        work_root.mkdir(parents=True, exist_ok=True)
        test_file = work_root / ".sp_write_test"
        test_file.write_text("ok", encoding="ascii")
        test_file.unlink()
        writable = True
    except OSError:
        writable = False
    add("work_root_writable", writable, str(work_root))

    diagnostics_output = work_root / "mimics_diagnostics.json"
    process_result = None
    if run_diagnostics and executable.is_file() and (script_dir / "sp_diagnostics.py").is_file():
        log_path = work_root / "mimics_diagnostics.log"
        command = [
            str(executable),
            "-background_mode",
            "-save_log",
            str(log_path),
            "-run_script",
            str(script_dir / "sp_diagnostics.py"),
            str(diagnostics_output),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=int(config.get("doctor_timeout_seconds", 180)))
        process_result = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "diagnostics_output": str(diagnostics_output),
        }
        add(
            "mimics_diagnostics",
            diagnostics_output.is_file(),
            f"returncode={completed.returncode}, output_exists={diagnostics_output.is_file()}",
        )
        if diagnostics_output.is_file():
            diagnostics = load_data(diagnostics_output)
            actual_version = str(diagnostics.get("mimics_version", ""))
            expected_version = str(config.get("expected_version", "21.0"))
            add(
                "mimics_version",
                expected_version in actual_version,
                f"expected {expected_version}, detected {actual_version}",
            )

    report = {
        "schema_version": "mimics_doctor_report.v1",
        "created_at": utc_now(),
        "config_path": str(config_path.resolve()),
        "expected_product": config.get("expected_product", "Mimics Research"),
        "expected_version": str(config.get("expected_version", "21.0")),
        "checks": checks,
        "process": process_result,
        "status": "ready" if all(item["passed"] for item in checks) else "blocked",
    }
    report_path = work_root / "mimics_doctor_report.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report
