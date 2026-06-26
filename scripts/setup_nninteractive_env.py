#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot setup for nnInteractive environment.

Creates an isolated Python virtual environment with PyTorch, nnInteractive,
and downloads model weights from HuggingFace.

Usage:
    python scripts/setup_nninteractive_env.py [--cuda auto] [--mirror tsinghua]

CUDA auto-detection:
    --cuda auto (default): detect from nvidia-smi / nvcc / CUDA_PATH
    --cuda cu124|cu121|cu118: explicit CUDA version
    --cuda cpu: skip GPU, install CPU-only PyTorch

Mirror support:
    --mirror tsinghua:  https://pypi.tuna.tsinghua.edu.cn/simple
    --mirror aliyun:    https://mirrors.aliyun.com/pypi/simple
    --mirror ustc:      https://pypi.mirrors.ustc.edu.cn/simple
    --mirror tencent:   https://mirrors.cloud.tencent.com/pypi/simple
    --mirror huawei:    https://repo.huaweicloud.com/repository/pypi/simple
    --mirror <url>:     custom mirror URL

    PyTorch CUDA wheels use a separate index (not mirrored by all providers).
    This script always uses the official PyTorch CUDA index for PyTorch
    installation, while using the mirror for all other packages.
    For providers that DO mirror PyTorch wheels (Tsinghua, Aliyun, SJTU),
    the PyTorch CUDA index is also replaced with the mirrored equivalent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_DIR = PROJECT_ROOT / "nninteractive_env"
VENV_PYTHON = (
    ENV_DIR / "Scripts" / "python.exe" if sys.platform == "win32"
    else ENV_DIR / "bin" / "python"
)
CONFIG_PATH = PROJECT_ROOT / "nninteractive_config.json"

HF_REPO = "nnInteractive/nnInteractive"
MODEL_NAME = "nnInteractive_v1.0"
MODEL_DIR = ENV_DIR / "models"
NNINTERACTIVE_VERSION = "2.4.2"
PYTORCH_VERSION = "2.6.0"

# Official PyTorch CUDA wheel indexes.
_PYTORCH_CUDA_INDEXES = {
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cu118": "https://download.pytorch.org/whl/cu118",
}

# Mirrors that also host PyTorch CUDA wheels (for even faster downloads).
_PYTORCH_CUDA_MIRRORS: dict[str, dict[str, str]] = {
    "tsinghua": {
        "cu124": "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/",
        "cu121": "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/",
        "cu118": "https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/pytorch/",
    },
    "aliyun": {
        "cu124": "https://mirrors.aliyun.com/pytorch-wheels/cu124/",
        "cu121": "https://mirrors.aliyun.com/pytorch-wheels/cu121/",
        "cu118": "https://mirrors.aliyun.com/pytorch-wheels/cu118/",
    },
}

# Pre-defined PyPI mirror aliases.
_PYPI_MIRRORS: dict[str, str] = {
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "aliyun":   "https://mirrors.aliyun.com/pypi/simple",
    "ustc":     "https://pypi.mirrors.ustc.edu.cn/simple",
    "tencent":  "https://mirrors.cloud.tencent.com/pypi/simple",
    "huawei":   "https://repo.huaweicloud.com/repository/pypi/simple",
}

# HuggingFace mirror endpoint (for model weight downloads).
_HF_MIRRORS: dict[str, str] = {
    "tsinghua": "https://hf-mirror.com",
}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


# ---------------------------------------------------------------------------
#  CUDA auto-detection
# ---------------------------------------------------------------------------

def _detect_cuda_version() -> str | None:
    """Auto-detect the installed CUDA toolkit version.

    Returns a string like "cu124", "cu121", etc., or None if no CUDA is found.
    """
    methods: list[tuple[str, str | None]] = []

    # Method 1: nvidia-smi (shows driver-supported CUDA version).
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=15,
            **(dict(startupinfo=_hidden_startupinfo()) if os.name == "nt" else {}),
        )
        if result.returncode == 0:
            match = re.search(r"CUDA Version:\s*(\d+\.\d+)", result.stdout)
            if match:
                version = match.group(1)
                methods.append(("nvidia-smi", version))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Method 2: nvcc --version.
    try:
        result = subprocess.run(
            ["nvcc", "--version"], capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            match = re.search(r"release\s+(\d+\.\d+)", result.stdout)
            if match:
                version = match.group(1)
                methods.append(("nvcc", version))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Method 3: CUDA_PATH / CUDA_HOME environment variable.
    for var in ("CUDA_PATH", "CUDA_HOME", "CUDA_ROOT"):
        path = os.environ.get(var, "")
        if path and os.path.isdir(path):
            # Look for version file.
            version_file = os.path.join(path, "version.txt")
            if os.path.isfile(version_file):
                try:
                    text = Path(version_file).read_text().strip()
                    match = re.search(r"(\d+\.\d+)", text)
                    if match:
                        methods.append((var, match.group(1)))
                except OSError:
                    pass

    if not methods:
        return None

    # Use the first detected version.
    source, version = methods[0]
    major, minor = version.split(".")[:2]
    cuda_key = f"cu{major}{minor}"

    print(f"  [auto-detect] CUDA {version} found via {source} → {cuda_key}")

    # Map to a known CUDA index.
    if cuda_key in _PYTORCH_CUDA_INDEXES:
        return cuda_key

    # Try to find the closest matching version.
    known = sorted(_PYTORCH_CUDA_INDEXES.keys())
    cuda_int = int(major) * 100 + int(minor)
    for key in known:
        key_int = int(key[2:4]) * 100 + int(key[4:6]) if len(key) >= 6 else 0
        if cuda_int >= key_int:
            best = key
    print(f"  [auto-detect] No exact match for {cuda_key}, using {best}")
    return best


def _hidden_startupinfo():
    """Windows: hide console window."""
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return startupinfo


# ---------------------------------------------------------------------------
#  Steps
# ---------------------------------------------------------------------------

def _pip_install(packages: list[str], *,
                  index_url: str | None = None,
                  extra_index_url: str | None = None,
                  find_links: str | None = None,
                  **extra_flags: bool) -> None:
    """Run pip install with layered index/mirror support.

    - index_url: primary index (if set, replaces default PyPI).
    - extra_index_url: fallback index (checked after index_url).
    - find_links: additional wheel links (-f flag, for PyTorch CUDA wheels).
    """
    cmd = [str(VENV_PYTHON), "-m", "pip", "install", "--no-warn-script-location"]
    if index_url:
        cmd.extend(["--index-url", index_url])
    if extra_index_url:
        cmd.extend(["--extra-index-url", extra_index_url])
    if find_links:
        cmd.extend(["--find-links", find_links])
    for flag, value in extra_flags.items():
        if value:
            cmd.append(f"--{flag.replace('_', '-')}")
    cmd.extend(packages)
    run(cmd)


def create_venv() -> None:
    """Create or repair the isolated Python environment."""
    if VENV_PYTHON.is_file():
        try:
            run([str(VENV_PYTHON), "-c",
                 "import sys; assert sys.version_info >= (3, 10)"])
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
        if sys.version_info < (3, 10):
            for candidate in ["python3.12", "python3.11", "python3.10", "python3"]:
                found = shutil.which(candidate)
                if found:
                    python_exe = found
                    break
            else:
                raise RuntimeError("Python 3.10+ is required")
        run([python_exe, "-m", "venv", str(ENV_DIR)])
        if not VENV_PYTHON.is_file():
            raise RuntimeError(
                f"virtual environment did not create {VENV_PYTHON}")
    except Exception:
        if preserved_models is not None and preserved_models.exists():
            ENV_DIR.mkdir(parents=True, exist_ok=True)
            preserved_models.replace(ENV_DIR / "models")
        raise
    else:
        if preserved_models is not None and preserved_models.exists():
            preserved_models.replace(ENV_DIR / "models")
        print(f"  Created: {ENV_DIR}")


def install_pytorch(cuda_version: str, mirror_alias: str | None = None) -> str:
    """Install PyTorch with CUDA support.

    Returns the actual device string (e.g. "cuda:0" or "cpu").
    """
    if cuda_version == "cpu":
        print("Installing PyTorch (CPU-only) ...")
        _pip_install(
            [f"torch=={PYTORCH_VERSION}"],
            index_url=(_resolve_pypi_mirror(mirror_alias)
                       if mirror_alias else None),
        )
        return "cpu"

    if cuda_version not in _PYTORCH_CUDA_INDEXES:
        print(f"ERROR: Unknown CUDA version '{cuda_version}'. "
              f"Choose from: {list(_PYTORCH_CUDA_INDEXES)} or 'cpu'.")
        sys.exit(1)

    # Determine the best PyTorch CUDA index.
    pytorch_index = _PYTORCH_CUDA_INDEXES[cuda_version]

    # If the selected mirror also hosts PyTorch CUDA wheels, use that instead.
    # NOTE: Some mirrors (e.g. Tsinghua) may not carry Windows CUDA wheels for
    # all torch versions.  When a mirror is used, we use a layered approach:
    # mirror as primary index (for standard deps) + PyTorch CUDA index as
    # extra-index (for the torch CUDA wheel itself).  This avoids the "no
    # matching distribution" error when the mirror lacks the CUDA wheel.
    if mirror_alias and mirror_alias in _PYTORCH_CUDA_MIRRORS:
        cuda_mirrors = _PYTORCH_CUDA_MIRRORS[mirror_alias]
        if cuda_version in cuda_mirrors:
            pytorch_index = cuda_mirrors[cuda_version]
            print(f"  Using {mirror_alias} mirror for PyTorch CUDA wheels: "
                  f"{pytorch_index}")

    print(f"Installing PyTorch {PYTORCH_VERSION} ({cuda_version}) ...")

    # When a mirror is specified, use it as the primary index (for fast
    # dependency downloads) and the PyTorch CUDA index as extra-index
    # (for the torch CUDA wheel).  This avoids slow downloads of deps
    # like sympy from the PyTorch index, and also handles mirrors that
    # don't carry the CUDA wheel for the current platform/version.
    mirror_url = _resolve_pypi_mirror(mirror_alias)
    if mirror_url:
        _pip_install(
            [f"torch=={PYTORCH_VERSION}"],
            index_url=mirror_url,
            extra_index_url=pytorch_index,
        )
    else:
        _pip_install(
            [f"torch=={PYTORCH_VERSION}"],
            index_url=pytorch_index,
        )

    # Verify CUDA is actually usable.
    print("  Verifying PyTorch CUDA ...")
    result = subprocess.run(
        [str(VENV_PYTHON), "-c",
         "import torch; "
         "print('torch', torch.__version__); "
         "print('cuda_available', torch.cuda.is_available()); "
         "print('cuda_version', torch.version.cuda if torch.cuda.is_available() else 'N/A')"],
        capture_output=True, text=True, timeout=60,
    )
    print(f"  {result.stdout.strip()}")

    if "cuda_available True" not in result.stdout:
        # PyTorch CUDA is installed but not usable. Diagnose why.
        diag = subprocess.run(
            [str(VENV_PYTHON), "-c",
             "import torch, sys; "
             "print('PyTorch build:', torch.__config__.show()); "
             "print(); "
             "print('sys.platform:', sys.platform); "],
            capture_output=True, text=True, timeout=60,
        )
        print()
        print("=" * 60)
        print("  WARNING: PyTorch CUDA is installed but NOT usable.")
        print("  Possible causes:")
        print("    1. No NVIDIA GPU in this machine.")
        print("    2. NVIDIA driver not installed or too old.")
        print("    3. CUDA toolkit version mismatch with driver.")
        print()
        print("  PyTorch build info:")
        for line in diag.stdout.strip().split("\n"):
            print(f"    {line}")
        print()
        print("  nnInteractive will FALL BACK to CPU inference.")
        print("  To skip this warning, use --cuda cpu.")
        print("=" * 60)
        print()
        return "cpu"

    return f"cuda:0"


def _resolve_pypi_mirror(mirror: str | None) -> str | None:
    """Resolve a mirror alias or URL to an index URL."""
    if mirror is None:
        return None
    if mirror in _PYPI_MIRRORS:
        return _PYPI_MIRRORS[mirror]
    if mirror.startswith("http://") or mirror.startswith("https://"):
        return mirror
    print(f"WARNING: Unknown mirror alias '{mirror}'. "
          f"Known: {list(_PYPI_MIRRORS)}. Proceeding without mirror.")
    return None


def install_packages(mirror_alias: str | None = None) -> None:
    """Install nnInteractive and required bridge dependencies.

    Uses the specified mirror for faster downloads (standard PyPI packages only;
    PyTorch CUDA wheels are handled separately in install_pytorch).
    """
    print("Installing nnInteractive and dependencies ...")
    mirror_url = _resolve_pypi_mirror(mirror_alias)
    if mirror_url:
        print(f"  Using mirror: {mirror_url}")

    packages = [
        f"nninteractive=={NNINTERACTIVE_VERSION}",
        "nibabel>=5.2",
        "huggingface_hub",
    ]
    _pip_install(packages, index_url=mirror_url)


def download_weights(mirror_alias: str | None = None) -> None:
    """Download nnInteractive model weights from HuggingFace.

    Supports HF mirror for faster downloads in regions with slow access
    to huggingface.co.
    """
    model_path = MODEL_DIR / MODEL_NAME
    if model_path.is_dir() and (model_path / "inference_session_class.json").is_file():
        print(f"[skip] Model weights already present: {model_path}")
        return

    print(f"Downloading model weights to {MODEL_DIR} ...")
    print("  This may take a few minutes (~400 MB).")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Set HF endpoint mirror if requested.
    hf_endpoint = ""
    if mirror_alias and mirror_alias in _HF_MIRRORS:
        hf_endpoint = f'os.environ["HF_ENDPOINT"] = "{_HF_MIRRORS[mirror_alias]}"\n'
        print(f"  Using HF mirror: {_HF_MIRRORS[mirror_alias]}")

    run(
        [
            str(VENV_PYTHON), "-c",
            f"""
import os
{hf_endpoint}os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
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
        print("Try: huggingface-cli download {0}/{1} "
              "--include '{1}/*' --local-dir {2}".format(
                  HF_REPO, MODEL_NAME, MODEL_DIR))
        sys.exit(1)

    print(f"  Model ready: {model_path}")


def verify_runtime() -> None:
    """Verify the installed environment can load all required packages."""
    model_path = MODEL_DIR / MODEL_NAME
    folds = sorted(
        path.name
        for path in model_path.glob("fold_*")
        if (path / "checkpoint_final.pth").is_file()
    )
    if not folds:
        raise RuntimeError(
            f"No fold_*/checkpoint_final.pth was found under {model_path}"
        )
    print("Verifying nnInteractive runtime ...")
    run(
        [
            str(VENV_PYTHON),
            "-c",
            "import nibabel,numpy,torch,nnInteractive;"
            "print('python runtime OK');"
            "print('torch',torch.__version__);"
            "print('cuda_available',torch.cuda.is_available())",
        ]
    )
    print(f"  Model folds: {', '.join(folds)}")


def create_server_scripts(device: str) -> None:
    """Create scripts to manually start/stop the server."""
    model_path = MODEL_DIR / MODEL_NAME
    if not (model_path / "inference_session_class.json").is_file():
        print("ERROR: Model weights not found. Run download_weights first.")
        sys.exit(1)

    # Windows batch file.
    bat_path = ENV_DIR / "start_server.bat"
    bat_content = f"""@echo off
setlocal

set "PYTHON={VENV_PYTHON}"
set "MODEL_DIR={model_path}"
set "DEVICE={device}"
set "HOST=127.0.0.1"
set "PORT=1527"

if /I "%DEVICE%"=="auto" (
    for /f "delims=" %%D in ('"%PYTHON%" -c "import torch; print('cuda:0' if torch.cuda.is_available() else 'cpu')"') do set "DEVICE=%%D"
)

echo ============================================================
echo  nnInteractive Server
echo  Model:  %MODEL_DIR%
echo  Device: %DEVICE%
echo  URL:    http://%HOST%:%PORT%
echo ============================================================

"%PYTHON%" -m nnInteractive.inference.server.main ^
    --model-dir "%MODEL_DIR%" ^
    --host %HOST% ^
    --port %PORT% ^
    --device %DEVICE%

endlocal
pause
"""
    bat_path.write_text(bat_content, encoding="ascii")
    print(f"  Created: {bat_path}")

    # Linux/macOS shell script.
    sh_path = ENV_DIR / "bin" / "start_server.sh"
    sh_content = f"""#!/usr/bin/env bash
set -euo pipefail

PYTHON="{VENV_PYTHON}"
MODEL_DIR="{model_path}"
DEVICE="{device}"
HOST="127.0.0.1"
PORT="1527"

if [[ "$DEVICE" == "auto" ]]; then
    DEVICE="$("$PYTHON" -c "import torch; print('cuda:0' if torch.cuda.is_available() else 'cpu')")"
fi

echo "============================================================"
echo " nnInteractive Server"
echo " Model:  $MODEL_DIR"
echo " Device: $DEVICE"
echo " URL:    http://$HOST:$PORT"
echo "============================================================"

exec "$PYTHON" -m nnInteractive.inference.server.main \\
    --model-dir "$MODEL_DIR" \\
    --host "$HOST" \\
    --port "$PORT" \\
    --device "$DEVICE"
"""
    sh_path.parent.mkdir(parents=True, exist_ok=True)
    sh_path.write_text(sh_content, encoding="utf-8")
    sh_path.chmod(0o755)
    print(f"  Created: {sh_path}")

    # Health check script.
    check_path = ENV_DIR / "bin" / "check_server.sh"
    check_content = """#!/usr/bin/env bash
echo "Checking nnInteractive server ..."
curl -s http://127.0.0.1:1527/healthz | python3 -m json.tool 2>/dev/null || echo "Server not reachable"
"""
    check_path.write_text(check_content, encoding="utf-8")
    check_path.chmod(0o755)
    print(f"  Created: {check_path}")


def write_runtime_config(device: str) -> None:
    """Write nninteractive_config.json for the Mimics adapter."""
    config = {
        "schema_version": "nninteractive_config.v1",
        "python": str(VENV_PYTHON),
        "bridge_script": str(
            PROJECT_ROOT / "adapters" / "mimics" / "nninteractive_bridge.py"),
        "model_dir": str(MODEL_DIR / MODEL_NAME),
        "server_url": "http://127.0.0.1:1527",
        "auto_start_server": True,
        "server_idle_timeout_seconds": 1800,
        "server_startup_timeout_seconds": 600,
        "set_image_timeout_seconds": 1800,
        "prediction_timeout_seconds": 1800,
        "bridge_timeout_seconds": 4200,
        "environment_probe_timeout_seconds": 180,
        "allow_cpu_fallback": True,
        "execution_mode": "async",
        "fold": "auto",
        "reuse_session": True,
        "device": device,
        "env_dir": str(ENV_DIR),
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"  Config written: {CONFIG_PATH}")


def print_instructions(device: str) -> None:
    """Print post-setup instructions."""
    print()
    print("=" * 64)
    print("  nnInteractive setup complete!")
    print("=" * 64)
    print()
    print(f"  Device: {device}")
    print(f"  Environment: {ENV_DIR}")
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
    print("=" * 64)


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set up nnInteractive environment for Mimics integration."
    )
    parser.add_argument(
        "--cuda",
        default="auto",
        help=(
            "CUDA version for PyTorch. "
            "'auto' (default): auto-detect from system. "
            "'cpu': install CPU-only PyTorch. "
            "Explicit: cu124, cu121, cu118."
        ),
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="Torch device for inference (default: auto).",
    )
    parser.add_argument(
        "--mirror",
        default=None,
        help=(
            "PyPI mirror for faster package downloads. "
            "Pre-defined: tsinghua, aliyun, ustc, tencent, huawei. "
            "Or provide a full mirror URL. "
            "PyTorch CUDA wheels use a dedicated index (with mirror fallback "
            "for providers that support it)."
        ),
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip model weight download.",
    )
    args = parser.parse_args()

    # Resolve CUDA version.
    cuda_version = args.cuda.strip().lower()
    if cuda_version == "auto":
        detected = _detect_cuda_version()
        if detected:
            cuda_version = detected
        else:
            print("  [auto-detect] No CUDA toolkit found. Using CPU mode.")
            print("  To install CUDA PyTorch anyway, use --cuda cu124 (or cu121/cu118).")
            cuda_version = "cpu"

    mirror_alias = args.mirror.strip() if args.mirror else None
    if mirror_alias and mirror_alias not in _PYPI_MIRRORS and \
       not mirror_alias.startswith("http"):
        print(f"  WARNING: Unknown mirror '{mirror_alias}'. "
              f"Known: {list(_PYPI_MIRRORS)}. Proceeding without mirror.")
        mirror_alias = None

    print("Setting up nnInteractive environment ...")
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Environment:  {ENV_DIR}")
    print(f"  CUDA version: {cuda_version}")
    if mirror_alias:
        print(f"  Mirror:       {mirror_alias}")
    print()

    create_venv()
    resolved_device = install_pytorch(cuda_version, mirror_alias)
    install_packages(mirror_alias)
    if not args.skip_download:
        download_weights(mirror_alias)
    verify_runtime()
    create_server_scripts(resolved_device)
    write_runtime_config(resolved_device)
    print_instructions(resolved_device)


if __name__ == "__main__":
    main()
