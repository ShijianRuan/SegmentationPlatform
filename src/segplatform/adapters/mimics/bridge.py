from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from segplatform.common import prefixed_sha256, utc_now, write_json
from segplatform.errors import ValidationError
from segplatform.imaging import BufferMapping, geometry_from_manifest, geometry_matches, read_mask, voxel_count
from segplatform.vocabulary import AnatomyVocabulary


DEFAULT_BUFFER_MAPPING = {
    "schema_version": "mimics_buffer_mapping.v1",
    "status": "unverified",
    "evidence_id": "",
    "platform_to_mimics_axes": [0, 1, 2],
    "platform_to_mimics_flips": [False, False, False],
}


def _mapping_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(value or DEFAULT_BUFFER_MAPPING)
    payload.setdefault("schema_version", "mimics_buffer_mapping.v1")
    payload.setdefault("status", "unverified")
    payload.setdefault("evidence_id", "")
    payload.setdefault("platform_to_mimics_axes", [0, 1, 2])
    payload.setdefault("platform_to_mimics_flips", [False, False, False])
    BufferMapping.from_config(payload)
    return payload


@dataclass(frozen=True)
class BufferMappingSet:
    default_data: dict[str, Any]
    by_image_id: dict[str, dict[str, Any]]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "BufferMappingSet":
        mapping_file = config.get("buffer_mapping_file")
        if mapping_file:
            data = load_mapping_data(Path(mapping_file).expanduser())
            if data.get("schema_version") == "mimics_buffer_mapping_set.v1":
                default_data = data.get("default") or data.get("buffer_mapping")
                by_image_id = data.get("by_image_id") or data.get("buffer_mapping_by_image_id") or {}
                return cls(
                    default_data=_mapping_payload(default_data),
                    by_image_id={str(key): _mapping_payload(value) for key, value in by_image_id.items()},
                )
            return cls(
                default_data=_mapping_payload(data),
                by_image_id={
                    str(key): _mapping_payload(value)
                    for key, value in (config.get("buffer_mapping_by_image_id") or {}).items()
                },
            )
        return cls(
            default_data=_mapping_payload(config.get("buffer_mapping")),
            by_image_id={
                str(key): _mapping_payload(value)
                for key, value in (config.get("buffer_mapping_by_image_id") or {}).items()
            },
        )

    def data_for_image(self, image_id: str) -> dict[str, Any]:
        return self.by_image_id.get(str(image_id), self.default_data)

    def for_image(self, image_id: str) -> BufferMapping:
        return BufferMapping.from_config(self.data_for_image(image_id))

    def evidence_by_image_id(self, image_ids: list[str]) -> dict[str, str]:
        return {image_id: self.data_for_image(image_id).get("evidence_id", "") for image_id in image_ids}


def load_mapping_data(path: Path) -> dict[str, Any]:
    from segplatform.common import load_data

    data = load_data(path)
    if data.get("schema_version") not in {"mimics_buffer_mapping.v1", "mimics_buffer_mapping_set.v1"}:
        raise ValidationError("buffer mapping schema_version must be mimics_buffer_mapping.v1 or mimics_buffer_mapping_set.v1")
    return data


def load_mapping(path: Path) -> BufferMapping:
    data = load_mapping_data(path)
    if data.get("schema_version") != "mimics_buffer_mapping.v1":
        raise ValidationError("load_mapping requires a single mimics_buffer_mapping.v1 file")
    return BufferMapping.from_config(data)


def prepare_import_buffers(case_root: Path, runtime: dict[str, Any], mapping_set: BufferMappingSet) -> list[dict[str, Any]]:
    manifest = json.loads((case_root / "manifest.json").read_text(encoding="utf-8"))
    entries = []
    for label in manifest.get("initial_labels", []):
        mapping = mapping_set.for_image(label["image_id"])
        mapping.require_verified()
        source_path = case_root / label["path"]
        array, geometry = read_mask(source_path)
        expected = geometry_from_manifest(next(item for item in manifest["image_sets"] if item["image_id"] == label["image_id"]))
        matches, reasons = geometry_matches(expected, geometry)
        if not matches:
            raise ValidationError(
                f"initial mask geometry mismatch for {label['image_id']}/{label['organ']}: "
                + "; ".join(reasons)
            )
        transformed = mapping.platform_to_mimics(np.asarray(array != 0, dtype=np.uint8))
        destination = case_root / "working" / "bridge" / "import" / label["image_id"] / f"{label['organ']}.u8"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(transformed.tobytes(order="C"))
        entries.append(
            {
                "direction": "import",
                "review_id": manifest["review"]["review_id"],
                "image_id": label["image_id"],
                "organ": label["organ"],
                "platform_shape": list(expected.shape),
                "mimics_shape": list(transformed.shape),
                "path": str(destination.resolve()),
                "sha256": prefixed_sha256(destination),
                "byte_count": destination.stat().st_size,
                "buffer_mapping_evidence_id": mapping.evidence_id,
                "source_label_id": label.get("label_id"),
                "source_label_sha256": label["sha256"],
            }
        )
    return entries


def read_export_buffer(
    entry: dict[str, Any],
    mapping: BufferMapping,
    *,
    case_root: Path | None = None,
) -> np.ndarray:
    mapping.require_verified()
    path = Path(entry["path"])
    if not path.is_absolute():
        if entry.get("path_base") != "package_root" or case_root is None:
            raise ValidationError(f"relative export buffer path requires path_base=package_root: {path}")
        path = case_root.resolve() / path
    path = path.resolve()
    if case_root is not None:
        resolved_root = case_root.resolve()
        if path != resolved_root and resolved_root not in path.parents:
            raise ValidationError(f"export buffer path escapes Case Package: {path}")
    raw = path.read_bytes()
    expected_bytes = voxel_count(entry["mimics_shape"])
    if len(raw) != expected_bytes:
        raise ValidationError(f"buffer byte count mismatch: {path}: {len(raw)} != {expected_bytes}")
    if prefixed_sha256(path) != entry["sha256"]:
        raise ValidationError(f"buffer checksum mismatch: {path}")
    mimics_array = np.frombuffer(raw, dtype=np.uint8).reshape(tuple(entry["mimics_shape"]), order="C")
    platform_array = mapping.mimics_to_platform(mimics_array)
    if tuple(platform_array.shape) != tuple(entry["platform_shape"]):
        raise ValidationError(
            f"inverse buffer mapping produced {platform_array.shape}, expected {entry['platform_shape']}"
        )
    return platform_array != 0


def write_buffer_manifest(case_root: Path, runtime: dict[str, Any], entries: list[dict[str, Any]]) -> Path:
    path = case_root / "working" / "bridge" / "buffer_manifest.json"
    write_json(
        path,
        {
            "schema_version": "mimics_buffer_manifest.v1",
            "review_id": runtime["review_id"],
            "created_at": utc_now(),
            "mapping": runtime.get("buffer_mapping"),
            "mapping_by_image_id": runtime.get("buffer_mapping_by_image_id", {}),
            "entries": entries,
        },
    )
    return path


def normalize_submission_entries(entries: list[dict[str, Any]]) -> None:
    vocabulary = AnatomyVocabulary()
    seen = set()
    for entry in entries:
        entry["organ"] = vocabulary.normalize(str(entry["organ"]))
        key = (entry["image_id"], entry["organ"])
        if key in seen:
            raise ValidationError(f"duplicate submission buffer: {key}")
        seen.add(key)
