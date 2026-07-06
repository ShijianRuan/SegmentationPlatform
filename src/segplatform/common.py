from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prefixed_sha256(path: Path) -> str:
    return "sha256:" + sha256_file(path)


def hash_directory(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def hash_file_set(paths: list[Path], *, root: Path) -> str:
    """Hash a stable file bundle without depending on absolute paths."""

    digest = hashlib.sha256()
    resolved_root = root.resolve()
    for path in sorted((item.resolve() for item in paths), key=lambda item: item.relative_to(resolved_root).as_posix()):
        relative = path.relative_to(resolved_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def load_data(path: Path) -> Any:
    suffixes = "".join(path.suffixes).lower()
    text = path.read_text(encoding="utf-8")
    if suffixes.endswith(".json"):
        return json.loads(text)
    if suffixes.endswith((".yaml", ".yml")):
        return yaml.safe_load(text)
    raise ValueError(f"unsupported structured file: {path}")


def write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_yaml(path: Path, value: Any) -> None:
    atomic_write_text(path, yaml.safe_dump(value, allow_unicode=True, sort_keys=False))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def copy_path(source: Path, destination: Path, *, mode: str = "copy") -> None:
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mode not in {"copy", "hardlink", "symlink"}:
        raise ValueError(f"unsupported copy mode: {mode}")
    if mode == "symlink":
        destination.symlink_to(source.resolve(), target_is_directory=source.is_dir())
        return
    if source.is_dir():
        if mode == "hardlink":
            for item in source.rglob("*"):
                relative = item.relative_to(source)
                target = destination / relative
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif item.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        os.link(item, target)
                    except OSError:
                        shutil.copy2(item, target)
            return
        shutil.copytree(source, destination)
    else:
        if mode == "hardlink":
            try:
                os.link(source, destination)
                return
            except OSError:
                pass
        shutil.copy2(source, destination)


def ensure_within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise ValueError(f"path escapes root {resolved_root}: {resolved_candidate}")
    return resolved_candidate


def canonical_id(value: str, field: str = "id") -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} cannot be empty")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in stripped):
        raise ValueError(f"{field} contains unsupported characters: {value!r}")
    return stripped
