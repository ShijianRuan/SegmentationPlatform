#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a portable nnInteractive bundle for distribution to annotator machines.

This script is run ONCE by the platform manager on a machine with internet
access. It produces a self-contained zip archive with the inference runtime,
weights, bridge, and Mimics scripts. The target Windows workstation still
needs a compatible NVIDIA driver and a licensed Mimics Research 21 install.

Principle:
  - Embed the official Windows Python 3.12 embeddable distribution
  - pip-install all dependencies into it via --target
  - Download model weights from HuggingFace
  - Make all paths relative so the bundle works from any location
  - Zip it up (~5 GB)

Usage (manager runs once):
    python scripts/build_nninteractive_bundle.py

Output:
    nninteractive_bundle.zip

Annotator usage (each annotator does once):
    unzip nninteractive_bundle.zip -d D:\\\\MimicsTools\\\\
    # Point Mimics Scripting Library to:
    # D:\\MimicsTools\\nninteractive_env\\mimics\\scripting_library
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_NAME = "nninteractive_bundle"
BUILD_DIR = PROJECT_ROOT / "build" / BUNDLE_NAME
ENV_DIR_NAME = "nninteractive_env"
MODEL_NAME = "nnInteractive_v1.0"
MODEL_REPO = "nnInteractive/nnInteractive"
NNINTERACTIVE_VERSION = "2.4.2"

# PyTorch wheels by CUDA version.
PYTORCH_VERSION = "2.6.0"
_PYTORCH_CUDA_INDEXES = {
    "cu124": "https://download.pytorch.org/whl/cu124",
    "cu121": "https://download.pytorch.org/whl/cu121",
    "cu118": "https://download.pytorch.org/whl/cu118",
}
# Mirrors that also host PyTorch CUDA wheels.
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
_PYPI_MIRRORS: dict[str, str] = {
    "tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "aliyun":   "https://mirrors.aliyun.com/pypi/simple",
    "ustc":     "https://pypi.mirrors.ustc.edu.cn/simple",
    "tencent":  "https://mirrors.cloud.tencent.com/pypi/simple",
    "huawei":   "https://repo.huaweicloud.com/repository/pypi/simple",
}
_HF_MIRRORS: dict[str, str] = {
    "tsinghua": "https://hf-mirror.com",
}

# Python embeddable distribution for Windows.
PYTHON_VERSION = "3.12.9"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


def _detect_cuda_version() -> str | None:
    """Auto-detect installed CUDA version. Returns "cu124" etc. or None."""
    try:
        result = subprocess.run(
            ["nvidia-smi"], capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            match = re.search(r"CUDA Version:\s*(\d+\.\d+)", result.stdout)
            if match:
                major, minor = match.group(1).split(".")[:2]
                key = f"cu{major}{minor}"
                if key in _PYTORCH_CUDA_INDEXES:
                    return key
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _resolve_pypi_mirror(mirror: str | None) -> str | None:
    if mirror is None:
        return None
    if mirror in _PYPI_MIRRORS:
        return _PYPI_MIRRORS[mirror]
    if mirror.startswith("http://") or mirror.startswith("https://"):
        return mirror
    return None


# ---------------------------------------------------------------------------
#  Step 1: Set up portable Python
# ---------------------------------------------------------------------------

def _setup_portable_python_win(build_env: Path) -> Path:
    """Download and configure Python embeddable for Windows."""
    python_dir = build_env / ENV_DIR_NAME / "python"
    python_dir.mkdir(parents=True, exist_ok=True)
    python_exe = python_dir / "python.exe"

    if python_exe.is_file():
        print(f"[skip] Portable Python already present: {python_exe}")
        return python_exe

    print("Downloading Python embeddable distribution ...")
    embed_zip = build_env / "python-embed.zip"
    try:
        import urllib.request

        urllib.request.urlretrieve(PYTHON_EMBED_URL, embed_zip)
    except Exception as error:
        raise RuntimeError(
            "Could not download the Windows embeddable Python distribution. "
            "A system interpreter cannot be substituted because the resulting bundle "
            "would not be self-contained."
        ) from error

    print("  Extracting ...")
    shutil.unpack_archive(embed_zip, python_dir)

    # Enable pip in the embeddable distribution.
    # The embeddable distribution has a python*._pth file that we need to modify
    # to uncomment "import site" so that pip and site-packages work.
    pth_files = sorted(python_dir.glob("python*._pth"))
    for pth_file in pth_files:
        content = pth_file.read_text()
        # Uncomment "import site"
        content = content.replace("#import site", "import site")
        # Add Lib/site-packages to the path.
        if "../Lib/site-packages" not in content:
            content += "\n../Lib/site-packages\n"
        pth_file.write_text(content)

    # Install pip via get-pip.py.
    print("  Installing pip ...")
    get_pip = python_dir / "get-pip.py"
    try:
        import urllib.request

        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
    except Exception as error:
        raise RuntimeError(
            "Could not download get-pip.py; the portable bundle cannot be completed."
        ) from error

    run([str(python_exe), str(get_pip), "--no-warn-script-location"])

    # Also install pip directly using ensurepip.
    try:
        run([str(python_exe), "-m", "ensurepip", "--upgrade", "--default-pip"])
    except Exception:
        pass

    get_pip.unlink(missing_ok=True)
    return python_exe


def _setup_portable_python_linux(build_env: Path) -> Path:
    raise RuntimeError(
        "A Windows nnInteractive bundle must be built on Windows. "
        "Copied virtual environments are not reliably relocatable across systems."
    )


def setup_portable_python(build_env: Path) -> Path:
    """Set up a portable Python for the target platform."""
    if sys.platform == "win32":
        return _setup_portable_python_win(build_env)
    return _setup_portable_python_linux(build_env)


# ---------------------------------------------------------------------------
#  Step 2: Install packages
# ---------------------------------------------------------------------------

def install_packages(python_exe: Path, site_packages: Path,
                      cuda_version: str = "cu124",
                      mirror_alias: str | None = None) -> str:
    """Install nnInteractive and all dependencies into the bundle.

    Returns the resolved device string ("cuda:0" or "cpu").
    """
    marker = site_packages / "nnInteractive" / "__init__.py"
    if marker.is_file():
        print(f"[skip] Packages already installed: {site_packages}")
        return f"cuda:0" if cuda_version != "cpu" else "cpu"

    print("Installing PyTorch + nnInteractive + dependencies ...")
    site_packages.mkdir(parents=True, exist_ok=True)

    pip_base = [
        str(python_exe), "-m", "pip", "install",
        "--target", str(site_packages),
        "--no-warn-script-location",
        "--prefer-binary",
    ]

    # Resolve PyTorch CUDA index.
    if cuda_version == "cpu":
        pytorch_index = _resolve_pypi_mirror(mirror_alias)
        print("  Installing PyTorch (CPU-only) ...")
    else:
        if cuda_version not in _PYTORCH_CUDA_INDEXES:
            print(f"ERROR: Unknown CUDA version '{cuda_version}'.")
            sys.exit(1)
        pytorch_index = _PYTORCH_CUDA_INDEXES[cuda_version]
        if mirror_alias and mirror_alias in _PYTORCH_CUDA_MIRRORS:
            mirrors = _PYTORCH_CUDA_MIRRORS[mirror_alias]
            if cuda_version in mirrors:
                pytorch_index = mirrors[cuda_version]
                print(f"  Using {mirror_alias} mirror for PyTorch CUDA wheels")
        print(f"  Installing PyTorch {PYTORCH_VERSION} ({cuda_version}) ...")

    pytorch_cmd = pip_base + [f"torch=={PYTORCH_VERSION}"]
    if pytorch_index:
        pytorch_cmd.extend(["--index-url", pytorch_index])
    run(pytorch_cmd)

    # Verify CUDA in the target Python.
    if cuda_version != "cpu":
        print("  Verifying PyTorch CUDA ...")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(site_packages)
        result = subprocess.run(
            [str(python_exe), "-c",
             "import torch; "
             "print('torch', torch.__version__); "
             "print('cuda_available', torch.cuda.is_available()); "
             "print('cuda_version', torch.version.cuda "
             "if torch.cuda.is_available() else 'N/A')"],
            capture_output=True, text=True, timeout=60, env=env,
        )
        print(f"  {result.stdout.strip()}")
        if "cuda_available True" not in result.stdout:
            print("  WARNING: PyTorch CUDA wheel installed but GPU not usable.")
            print("  The bundle will fall back to CPU on GPU-less machines.")
            print("  This is expected if the build machine has no NVIDIA GPU.")

    # Install nnInteractive and bridge dependencies.
    pypi_index = _resolve_pypi_mirror(mirror_alias)
    pkg_cmd = pip_base + [
        f"nninteractive=={NNINTERACTIVE_VERSION}",
        "nibabel>=5.2",
        "huggingface_hub",
    ]
    if pypi_index:
        pkg_cmd.extend(["--index-url", pypi_index])
        print(f"  Using mirror for packages: {pypi_index}")
    run(pkg_cmd)

    return f"cuda:0" if cuda_version != "cpu" else "cpu"


# ---------------------------------------------------------------------------
#  Step 3: Download model weights
# ---------------------------------------------------------------------------

def download_weights(build_env: Path, python_exe: Path, site_packages: Path) -> Path:
    """Download nnInteractive model weights from HuggingFace."""
    model_path = build_env / ENV_DIR_NAME / "models" / MODEL_NAME
    if (model_path / "inference_session_class.json").is_file():
        print(f"[skip] Model weights already present: {model_path}")
        return model_path

    print("Downloading model weights (~400 MB) ...")
    model_path.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(site_packages)
    run(
        [
            str(python_exe), "-c",
            f"""
import os, sys
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="{MODEL_REPO}",
    allow_patterns=["{MODEL_NAME}/*"],
    local_dir="{model_path.parent}",
)
print("Download complete.")
""",
        ],
        env=env,
    )
    return model_path


# ---------------------------------------------------------------------------
#  Step 4: Create activation scripts
# ---------------------------------------------------------------------------

def create_activation_scripts(build_env: Path) -> None:
    """Create scripts that set up the Python path for the bundle."""
    (build_env / ENV_DIR_NAME).mkdir(parents=True, exist_ok=True)
    # Windows batch file to run any Python script in the bundle env.
    if sys.platform == "win32":
        bat = build_env / ENV_DIR_NAME / "python_env.bat"
        bat.write_text(
            "@echo off\r\n"
            'set "NNI_PYTHON=%~dp0python\\python.exe"\r\n'
            'set "PYTHONPATH=%~dp0Lib\\site-packages"\r\n'
            '"%NNI_PYTHON%" %*\r\n',
            encoding="ascii",
        )

    # Shell script for Linux.
    sh = build_env / ENV_DIR_NAME / "python_env.sh"
    sh.write_text(
        "#!/usr/bin/env bash\n"
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        'export PYTHONPATH="$SCRIPT_DIR/Lib/site-packages"\n'
        'exec "$SCRIPT_DIR/python/bin/python" "$@"\n',
        encoding="utf-8",
    )
    sh.chmod(0o755)

    # Create the start_server.bat/sh inside the env.
    if sys.platform == "win32":
        server_bat = build_env / ENV_DIR_NAME / "start_server.bat"
        server_bat.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            'set "ROOT=%~dp0"\r\n'
            'set "PYTHON=%ROOT%python\\python.exe"\r\n'
            f'set "MODEL_DIR=%ROOT%models\\{MODEL_NAME}"\r\n'
            'set "HOST=127.0.0.1"\r\n'
            'set "PORT=1527"\r\n'
            'set "DEVICE=auto"\r\n'
            'set "PYTHONPATH=%ROOT%Lib\\site-packages"\r\n'
            'if /I "%DEVICE%"=="auto" (\r\n'
            '  for /f "delims=" %%D in (\'"%PYTHON%" -c "import torch; '
            "print('cuda:0' if torch.cuda.is_available() else 'cpu')\"') "
            'do set "DEVICE=%%D"\r\n'
            ')\r\n'
            'echo nnInteractive Server: http://%HOST%:%PORT%\r\n'
            '"%PYTHON%" -m nnInteractive.inference.server.main '
            '--model-dir "%MODEL_DIR%" '
            '--host %HOST% --port %PORT% '
            '--device %DEVICE% '
            '--idle-timeout-seconds 1800 '
            '--max-sessions 1\r\n'
            'endlocal\r\n'
            'pause\r\n',
            encoding="ascii",
        )


# ---------------------------------------------------------------------------
#  Step 5: Include standalone Mimics integration
# ---------------------------------------------------------------------------

def include_mimics_integration(build_env: Path) -> None:
    """Copy the standalone bridge and Mimics scripts into the bundle."""
    integration_root = build_env / ENV_DIR_NAME / "mimics"
    runtime_dir = integration_root / "runtime_py35"
    library_dir = integration_root / "scripting_library"
    for directory in (runtime_dir, library_dir):
        directory.mkdir(parents=True, exist_ok=True)

    shutil.copy2(
        PROJECT_ROOT / "adapters" / "mimics" / "runtime_py35" / "nninteractive_mimics.py",
        runtime_dir / "nninteractive_mimics.py",
    )
    shutil.copy2(
        PROJECT_ROOT / "adapters" / "mimics" / "scripting_library" / "nnInteractive.py",
        library_dir / "nnInteractive.py",
    )
    shutil.copy2(
        PROJECT_ROOT / "adapters" / "mimics" / "nninteractive_bridge.py",
        integration_root / "nninteractive_bridge.py",
    )


# ---------------------------------------------------------------------------
#  Step 6: Package into zip
# ---------------------------------------------------------------------------

def create_zip(build_env: Path) -> Path:
    """Package the bundle into a distributable zip file."""
    zip_path = PROJECT_ROOT / f"{BUNDLE_NAME}.zip"
    print(f"Creating {zip_path} ...")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        env_dir = build_env / ENV_DIR_NAME
        for file_path in sorted(env_dir.rglob("*")):
            if file_path.is_file() and "__pycache__" not in file_path.parts:
                arcname = file_path.relative_to(build_env)
                zf.write(file_path, arcname)

    size_gb = zip_path.stat().st_size / (1024 ** 3)
    print(f"  Bundle created: {zip_path} ({size_gb:.1f} GB)")
    return zip_path


# ---------------------------------------------------------------------------
#  Step 7: Verify
# ---------------------------------------------------------------------------

def verify_bundle(build_env: Path) -> bool:
    """Quick sanity check that the bundle can import key packages."""
    if sys.platform == "win32":
        python_exe = build_env / ENV_DIR_NAME / "python" / "python.exe"
    else:
        python_exe = build_env / ENV_DIR_NAME / "python" / "bin" / "python"

    site_packages = build_env / ENV_DIR_NAME / "Lib" / "site-packages"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(site_packages)

    checks = [
        ("import torch; print('torch', torch.__version__)", "PyTorch"),
        ("import nnInteractive; print('nnInteractive OK')", "nnInteractive"),
        ("import nibabel; print('nibabel', nibabel.__version__)", "nibabel"),
    ]
    all_ok = True
    for code, label in checks:
        try:
            result = subprocess.run(
                [str(python_exe), "-c", code],
                capture_output=True, text=True, env=env, timeout=30,
            )
            if result.returncode == 0:
                print(f"  [{label}] {result.stdout.strip()}")
            else:
                print(f"  [{label}] FAILED: {result.stderr.strip()}")
                all_ok = False
        except Exception as exc:
            print(f"  [{label}] ERROR: {exc}")
            all_ok = False
    return all_ok


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build portable nnInteractive bundle for annotator distribution."
    )
    parser.add_argument(
        "--cuda",
        default="auto",
        help=(
            "CUDA version for PyTorch. "
            "'auto' (default): auto-detect from system. "
            "'cpu': CPU-only PyTorch. "
            "Explicit: cu124, cu121, cu118."
        ),
    )
    parser.add_argument(
        "--mirror",
        default=None,
        help=(
            "PyPI mirror for faster downloads. "
            "Pre-defined: tsinghua, aliyun, ustc, tencent, huawei. "
            "Or provide a full mirror URL."
        ),
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip model weight download.",
    )
    parser.add_argument(
        "--skip-zip",
        action="store_true",
        help="Skip final zip packaging.",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Just verify an existing build.",
    )
    args = parser.parse_args()

    # Resolve CUDA version.
    cuda_version = args.cuda.strip().lower()
    if cuda_version == "auto":
        detected = _detect_cuda_version()
        if detected:
            cuda_version = detected
            print(f"[auto-detect] CUDA {cuda_version} found via nvidia-smi")
        else:
            cuda_version = "cu124"  # default for Windows GPU workstations
            print(f"[auto-detect] No CUDA found, defaulting to {cuda_version}")

    mirror_alias = args.mirror.strip() if args.mirror else None

    build_env = BUILD_DIR
    build_env.mkdir(parents=True, exist_ok=True)

    if args.verify_only:
        ok = verify_bundle(build_env)
        sys.exit(0 if ok else 1)

    print("=" * 60)
    print("  Building nnInteractive portable bundle")
    print(f"  Build directory: {build_env}")
    print(f"  Platform: {sys.platform}")
    print(f"  CUDA: {cuda_version}")
    if mirror_alias:
        print(f"  Mirror: {mirror_alias}")
    print("=" * 60)
    print()

    # Step 1: Portable Python.
    python_exe = setup_portable_python(build_env)
    print(f"  Python: {python_exe}\n")

    # Step 2: Install packages.
    site_packages = build_env / ENV_DIR_NAME / "Lib" / "site-packages"
    resolved_device = install_packages(python_exe, site_packages,
                                        cuda_version, mirror_alias)
    print()

    # Step 3: Download weights.
    if not args.skip_download:
        download_weights(build_env, python_exe, site_packages)
        print()

    # Step 4: Activation scripts.
    create_activation_scripts(build_env)
    print()

    # Step 5: Include the independent Mimics entry and bridge.
    include_mimics_integration(build_env)
    print()

    # Step 6: Verify.
    print("Verifying bundle ...")
    ok = verify_bundle(build_env)
    if not ok:
        print("\nBundle verification FAILED. Check errors above.")
        sys.exit(1)
    print()

    # Step 7: Zip.
    if not args.skip_zip:
        zip_path = create_zip(build_env)
        print()
        print("=" * 60)
        print("  Bundle ready for distribution!")
        print(f"  {zip_path}")
        print(f"  Device: {resolved_device}")
        print()
        print("  Unzip on the target Windows workstation:")
        print("  unzip nninteractive_bundle.zip -d D:\\MimicsTools\\")
        print("  Set Mimics Scripting Library to:")
        print("  D:\\MimicsTools\\nninteractive_env\\mimics\\scripting_library")
        print("=" * 60)
    else:
        print("=" * 60)
        print(f"  Build complete in: {build_env / ENV_DIR_NAME}")
        print(f"  Device: {resolved_device}")
        print("  Copy this directory to annotator machines.")
        print("=" * 60)


if __name__ == "__main__":
    main()
