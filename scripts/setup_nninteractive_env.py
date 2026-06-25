#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot setup for nnInteractive environment.

Creates an isolated Python virtual environment with PyTorch, nnInteractive,
and downloads model weights from HuggingFace.

Important: a virtual environment is not cross-platform portable. Build this
environment on the target Windows workstation, or build an offline Windows
bundle on a matching Windows machine and copy that bundle to the Mimics
workstation.

Usage:
    python scripts/setup_nninteractive_env.py [--cuda cu124] [--device cuda:0]

What this does:
    1. Creates a Python 3.10+ venv at ./nninteractive_env/
    2. Installs PyTorch with CUDA support
    3. Installs nnInteractive and its dependencies
    4. Installs nibabel for NIfTI I/O in the bridge
    5. Downloads model weights (~400 MB) from HuggingFace
    6. Creates optional manual-start diagnostics scripts
    7. Writes nninteractive_config.json

After setup, the Mimics bridge can auto-start the server. For manual checks:
    Windows: nninteractive_env\\\\start_server.bat
    Linux:   nninteractive_env/bin/start_server.sh

Verify:
    curl http://127.0.0.1:1527/healthz
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_DIR = PROJECT_ROOT / "nninteractive_env"
VENV_PYTHON = (
    ENV_DIR / "Scripts" / "python.exe" if sys.platform == "win32"
    else ENV_DIR / "bin" / "python"
)
CONFIG_PATH = PROJECT_ROOT / "nninteractive_config.json"

# HuggingFace model repository.
HF_REPO = "nnInteractive/nnInteractive"
MODEL_NAME = "nnInteractive_v1.0"
MODEL_DIR = ENV_DIR / "models"
NNINTERACTIVE_VERSION = "2.4.2"

# PyTorch CUDA index URLs by CUDA version.
CUDA_INDEXES = {
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cu118": "https://download.pytorch.org/whl/cu118",
}


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def create_venv() -> None:
    """Create or repair the isolated Python environment without redownloading weights."""
    if VENV_PYTHON.is_file():
        try:
            run([str(VENV_PYTHON), "-c", "import sys; assert sys.version_info >= (3, 10)"])
        except (OSError, subprocess.CalledProcessError):
            print(f"[repair] Existing Python is not usable: {VENV_PYTHON}")
        else:
            print(f"[skip] Virtual environment already exists: {ENV_DIR}")
            return

    preserved_models = None
    if ENV_DIR.exists():
        print(f"[repair] Incomplete virtual environment found: {ENV_DIR}")
        models = ENV_DIR / "models"
        if models.is_dir():
            preserved_models = PROJECT_ROOT / (
                ".nninteractive_models_recovery_" + uuid.uuid4().hex
            )
            models.replace(preserved_models)
        shutil.rmtree(ENV_DIR)

    try:
        print("Creating virtual environment ...")
        python_exe = sys.executable
        version_info = sys.version_info
        if version_info < (3, 10):
            for candidate in ["python3.12", "python3.11", "python3.10", "python3"]:
                found = shutil.which(candidate)
                if found:
                    python_exe = found
                    break
            else:
                raise RuntimeError("Python 3.10+ is required")

        run([python_exe, "-m", "venv", str(ENV_DIR)])
        if not VENV_PYTHON.is_file():
            raise RuntimeError(f"virtual environment did not create {VENV_PYTHON}")
    except Exception:
        if preserved_models is not None and preserved_models.exists():
            ENV_DIR.mkdir(parents=True, exist_ok=True)
            preserved_models.replace(ENV_DIR / "models")
        raise
    else:
        if preserved_models is not None and preserved_models.exists():
            preserved_models.replace(ENV_DIR / "models")
        print(f"  Created: {ENV_DIR}")


def install_pytorch(cuda_version: str) -> None:
    """Install PyTorch with CUDA support."""
    index_url = CUDA_INDEXES.get(cuda_version)
    if not index_url:
        print(f"ERROR: Unknown CUDA version '{cuda_version}'. Choose from: {list(CUDA_INDEXES)}")
        sys.exit(1)

    print(f"Installing PyTorch ({cuda_version}) ...")
    # Pin to a known-good PyTorch version.
    run(
        [
            str(VENV_PYTHON), "-m", "pip", "install",
            "torch==2.6.0",
            "--index-url", index_url,
        ]
    )


def install_packages() -> None:
    """Install nnInteractive and required bridge dependencies."""
    print("Installing nnInteractive and dependencies ...")

    packages = [
        "nninteractive=={0}".format(NNINTERACTIVE_VERSION),
        "nibabel>=5.2",
        "huggingface_hub",
    ]
    run(
        [str(VENV_PYTHON), "-m", "pip", "install"]
        + packages
    )


def download_weights() -> None:
    """Download nnInteractive model weights from HuggingFace."""
    model_path = MODEL_DIR / MODEL_NAME
    if model_path.is_dir() and (model_path / "inference_session_class.json").is_file():
        print(f"[skip] Model weights already present: {model_path}")
        return

    print(f"Downloading model weights to {MODEL_DIR} ...")
    print("  This may take a few minutes (~400 MB).")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    run(
        [
            str(VENV_PYTHON), "-c",
            f"""
import os
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="{HF_REPO}",
    allow_patterns=["{MODEL_NAME}/*"],
    local_dir="{MODEL_DIR}",
)
print("Download complete:", "{MODEL_DIR / MODEL_NAME}")
""",
        ]
    )

    # Verify download.
    expected = model_path / "inference_session_class.json"
    if not expected.is_file():
        print(f"ERROR: Model download incomplete. Missing: {expected}")
        print("Try: huggingface-cli download nnInteractive/nnInteractive --include 'nnInteractive_v1.0/*' --local-dir {0}".format(MODEL_DIR))
        sys.exit(1)

    print(f"  Model ready: {model_path}")


def create_server_scripts(device: str) -> None:
    """Create Windows batch file and Linux shell script to start/stop the server."""
    model_path = MODEL_DIR / MODEL_NAME
    if not (model_path / "inference_session_class.json").is_file():
        print("ERROR: Model weights not found. Run download_weights first.")
        sys.exit(1)

    # Windows batch file.
    bat_path = ENV_DIR / "start_server.bat"
    bat_content = f"""@echo off
REM Start nnInteractive inference server.
REM Usage: double-click this file, or run from command prompt.
REM Server runs on http://127.0.0.1:1527

setlocal

set "NNINTERACTIVE_ROOT={PROJECT_ROOT}"
set "PYTHON={VENV_PYTHON}"
set "MODEL_DIR={model_path}"
set "DEVICE={device}"
set "HOST=127.0.0.1"
set "PORT=1527"

echo ============================================================
echo  nnInteractive Server
echo  Model:  %MODEL_DIR%
echo  Device: %DEVICE%
echo  URL:    http://%HOST%:%PORT%
echo ============================================================
echo.
echo Starting server (press Ctrl+C to stop) ...
echo.

"%PYTHON%" -m nnInteractive.inference.server.main ^
    --model-dir "%MODEL_DIR%" ^
    --fold all ^
    --host %HOST% ^
    --port %PORT% ^
    --device %DEVICE%

endlocal
pause
"""
    bat_path.write_text(bat_content, encoding="ascii")
    print(f"  Created: {bat_path}")

    # Linux shell script.
    sh_path = ENV_DIR / "bin" / "start_server.sh"
    sh_content = f"""#!/usr/bin/env bash
set -euo pipefail

NNINTERACTIVE_ROOT="{PROJECT_ROOT}"
PYTHON="{VENV_PYTHON}"
MODEL_DIR="{model_path}"
DEVICE="{device}"
HOST="127.0.0.1"
PORT="1527"

echo "============================================================"
echo " nnInteractive Server"
echo " Model:  $MODEL_DIR"
echo " Device: $DEVICE"
echo " URL:    http://$HOST:$PORT"
echo "============================================================"
echo ""
echo "Starting server (press Ctrl+C to stop) ..."
echo ""

exec "$PYTHON" -m nnInteractive.inference.server.main \\
    --model-dir "$MODEL_DIR" \\
    --fold all \\
    --host "$HOST" \\
    --port "$PORT" \\
    --device "$DEVICE"
"""
    sh_path.parent.mkdir(parents=True, exist_ok=True)
    sh_path.write_text(sh_content, encoding="utf-8")
    sh_path.chmod(0o755)
    print(f"  Created: {sh_path}")

    # Health check script (Linux).
    check_path = ENV_DIR / "bin" / "check_server.sh"
    check_content = """#!/usr/bin/env bash
echo "Checking nnInteractive server ..."
curl -s http://127.0.0.1:1527/healthz | python3 -m json.tool 2>/dev/null || echo "Server not reachable"
"""
    check_path.write_text(check_content, encoding="utf-8")
    check_path.chmod(0o755)
    print(f"  Created: {check_path}")


def write_runtime_config(device: str) -> None:
    """Write nninteractive_config.json for the MIMICS adapter."""
    config = {
        "schema_version": "nninteractive_config.v1",
        "python": str(VENV_PYTHON),
        "bridge_script": str(PROJECT_ROOT / "adapters" / "mimics" / "nninteractive_bridge.py"),
        "model_dir": str(MODEL_DIR / MODEL_NAME),
        "server_url": "http://127.0.0.1:1527",
        "auto_start_server": True,
        "server_idle_timeout_seconds": 1800,
        "device": device,
        "env_dir": str(ENV_DIR),
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"  Config written: {CONFIG_PATH}")


def print_instructions() -> None:
    """Print post-setup instructions."""
    print()
    print("=" * 64)
    print("  nnInteractive setup complete!")
    print("=" * 64)
    print()
    print("Next steps:")
    print()
    if sys.platform == "win32":
        print("  1. Optional manual server check:")
        print(f"     {ENV_DIR / 'start_server.bat'}")
        print()
        print("  2. Verify it's running:")
        print("     curl http://127.0.0.1:1527/healthz")
    else:
        print("  1. Optional manual server check:")
        print(f"     {ENV_DIR / 'bin' / 'start_server.sh'}")
        print()
        print("  2. Verify it's running:")
        print(f"     {ENV_DIR / 'bin' / 'check_server.sh'}")
    print()
    print("  3. Optional environment overrides:")
    print(f"     NNINTERACTIVE_PYTHON={VENV_PYTHON}")
    print(f"     NNINTERACTIVE_MODEL_DIR={MODEL_DIR / MODEL_NAME}")
    print()
    print("  4. In Mimics, open any project, select one target Mask, then run:")
    print("     Script -> Scripting Library -> nnInteractive")
    print()
    print("The Mimics bridge can auto-start the server on first prediction.")
    print("Manual server startup is only needed for diagnostics; stop it with Ctrl+C")
    print("before returning to the default auto-managed mode.")
    print()
    print("=" * 64)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up nnInteractive environment for MIMICS integration."
    )
    parser.add_argument(
        "--cuda",
        default="cu124",
        choices=list(CUDA_INDEXES),
        help="CUDA version for PyTorch (default: cu124).",
    )
    parser.add_argument(
        "--device",
        default="cuda:0",
        help="Torch device for inference (default: cuda:0).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip model weight download.",
    )
    args = parser.parse_args()

    print("Setting up nnInteractive environment ...")
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Environment:  {ENV_DIR}")
    print()

    create_venv()
    install_pytorch(args.cuda)
    install_packages()
    if not args.skip_download:
        download_weights()
    create_server_scripts(args.device)
    write_runtime_config(args.device)
    print_instructions()


if __name__ == "__main__":
    main()
