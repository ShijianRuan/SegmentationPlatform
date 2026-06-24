#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a portable nnInteractive bundle for distribution to annotator machines.

This script is run ONCE by the platform manager on a machine with internet
access. It produces a self-contained zip archive that annotators simply
unzip into their SegmentationPlatform project directory — no Python, no pip,
no downloads, no GPU driver checks needed.

Principle:
  - Embed a portable Python 3.12 (Windows embeddable or Linux conda-standalone)
  - pip-install all dependencies into it via --target
  - Download model weights from HuggingFace
  - Make all paths relative so the bundle works from any location
  - Zip it up (~5 GB)

Usage (manager runs once):
    python scripts/build_nninteractive_bundle.py

Output:
    nninteractive_bundle.zip

Annotator usage (each annotator does once):
    unzip nninteractive_bundle.zip -d D:\\\\SegmentationPlatform\\\\
    # Done. No further steps.
"""

from __future__ import annotations

import argparse
import os
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

# PyTorch wheels by CUDA version (Windows, Python 3.12, CUDA 12.4).
PYTORCH_INDEX = "https://download.pytorch.org/whl/cu124"
PYTORCH_VERSION = "2.6.0"

# Python embeddable distribution for Windows.
PYTHON_VERSION = "3.12.9"
PYTHON_EMBED_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kwargs)


# ---------------------------------------------------------------------------
#  Step 1: Set up portable Python
# ---------------------------------------------------------------------------

def _setup_portable_python_win(build_env: Path) -> Path:
    """Download and configure Python embeddable for Windows."""
    python_dir = build_env / "python"
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
    except Exception:
        print("  Download failed. Falling back to system Python for the build.")
        return Path(sys.executable)

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
        if "Lib/site-packages" not in content:
            content += "\nLib/site-packages\n"
        pth_file.write_text(content)

    # Install pip via get-pip.py.
    print("  Installing pip ...")
    get_pip = python_dir / "get-pip.py"
    try:
        import urllib.request

        urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
    except Exception:
        print("  Could not download get-pip.py. Bundle won't have pip.")
        return python_exe

    run([str(python_exe), str(get_pip), "--no-warn-script-location"])

    # Also install pip directly using ensurepip.
    try:
        run([str(python_exe), "-m", "ensurepip", "--upgrade", "--default-pip"])
    except Exception:
        pass

    get_pip.unlink(missing_ok=True)
    return python_exe


def _setup_portable_python_linux(build_env: Path) -> Path:
    """On Linux, use the system Python and create a relocatable venv."""
    # We use --copies to copy rather than symlink the interpreter.
    venv_dir = build_env / "python"
    if not (venv_dir / "bin" / "python").is_file():
        run([sys.executable, "-m", "venv", "--copies", str(venv_dir)])
    return venv_dir / "bin" / "python"


def setup_portable_python(build_env: Path) -> Path:
    """Set up a portable Python for the target platform."""
    if sys.platform == "win32":
        return _setup_portable_python_win(build_env)
    return _setup_portable_python_linux(build_env)


# ---------------------------------------------------------------------------
#  Step 2: Install packages
# ---------------------------------------------------------------------------

def install_packages(python_exe: Path, site_packages: Path) -> None:
    """Install nnInteractive and all dependencies into the bundle."""
    marker = site_packages / "nnInteractive" / "__init__.py"
    if marker.is_file():
        print(f"[skip] Packages already installed: {site_packages}")
        return

    print("Installing PyTorch + nnInteractive + dependencies ...")

    # Create a temporary directory for pip target install.
    site_packages.mkdir(parents=True, exist_ok=True)

    pip_args = [
        str(python_exe), "-m", "pip", "install",
        "--target", str(site_packages),
        "--no-warn-script-location",
        "--prefer-binary",
    ]

    # Install PyTorch first (largest, most likely to fail).
    run(pip_args + [
        f"torch=={PYTORCH_VERSION}",
        "--index-url", PYTORCH_INDEX,
    ])

    # Install nnInteractive and bridge dependencies.
    run(pip_args + [
        "nninteractive>=2.4.0",
        "nibabel>=5.2",
        "huggingface_hub",
    ])


# ---------------------------------------------------------------------------
#  Step 3: Download model weights
# ---------------------------------------------------------------------------

def download_weights(build_env: Path, python_exe: Path, site_packages: Path) -> Path:
    """Download nnInteractive model weights from HuggingFace."""
    model_path = build_env / ENV_DIR_NAME / "models" / MODEL_NAME
    if (model_path / "inference_info.json").is_file():
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
    model_path = build_env / ENV_DIR_NAME / "models" / MODEL_NAME
    python_exe = build_env / ENV_DIR_NAME / "python" / "python.exe" if sys.platform == "win32" else build_env / ENV_DIR_NAME / "python" / "bin" / "python"

    if sys.platform == "win32":
        server_bat = build_env / ENV_DIR_NAME / "start_server.bat"
        server_bat.write_text(
            "@echo off\r\n"
            "setlocal\r\n"
            f'set "PYTHON={python_exe}"\r\n'
            f'set "MODEL_DIR={model_path}"\r\n'
            'set "HOST=127.0.0.1"\r\n'
            'set "PORT=1527"\r\n'
            'set "DEVICE=cuda:0"\r\n'
            f'set "PYTHONPATH={build_env / ENV_DIR_NAME / "Lib" / "site-packages"}"\r\n'
            'echo nnInteractive Server: http://%HOST%:%PORT%\r\n'
            '"%PYTHON%" -m nnInteractive.inference.server.main '
            '--model-dir "%MODEL_DIR%" --fold all '
            '--host %HOST% --port %PORT% '
            '--device %DEVICE% '
            '--idle-timeout-seconds 1800 '
            '--max-sessions 1\r\n'
            'endlocal\r\n'
            'pause\r\n',
            encoding="ascii",
        )


# ---------------------------------------------------------------------------
#  Step 5: Package into zip
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
#  Step 6: Verify
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

    build_env = BUILD_DIR
    build_env.mkdir(parents=True, exist_ok=True)

    if args.verify_only:
        ok = verify_bundle(build_env)
        sys.exit(0 if ok else 1)

    print("=" * 60)
    print("  Building nnInteractive portable bundle")
    print(f"  Build directory: {build_env}")
    print(f"  Platform: {sys.platform}")
    print("=" * 60)
    print()

    # Step 1: Portable Python.
    python_exe = setup_portable_python(build_env)
    print(f"  Python: {python_exe}\n")

    # Step 2: Install packages.
    site_packages = build_env / ENV_DIR_NAME / "Lib" / "site-packages"
    install_packages(python_exe, site_packages)
    print()

    # Step 3: Download weights.
    if not args.skip_download:
        download_weights(build_env, python_exe, site_packages)
        print()

    # Step 4: Activation scripts.
    create_activation_scripts(build_env)
    print()

    # Step 5: Verify.
    print("Verifying bundle ...")
    ok = verify_bundle(build_env)
    if not ok:
        print("\nBundle verification FAILED. Check errors above.")
        sys.exit(1)
    print()

    # Step 6: Zip.
    if not args.skip_zip:
        zip_path = create_zip(build_env)
        print()
        print("=" * 60)
        print("  Bundle ready for distribution!")
        print(f"  {zip_path}")
        print()
        print("  Annotators: unzip this file into your project directory.")
        print("  unzip nninteractive_bundle.zip -d D:\\SegmentationPlatform\\")
        print("  That\'s it — no Python, no pip, no downloads needed.")
        print("=" * 60)
    else:
        print("=" * 60)
        print(f"  Build complete in: {build_env / ENV_DIR_NAME}")
        print("  Copy this directory to annotator machines.")
        print("=" * 60)


if __name__ == "__main__":
    main()
