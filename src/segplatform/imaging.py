from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pydicom

from segplatform.common import hash_directory, prefixed_sha256
from segplatform.errors import ConfigurationError, ValidationError


@dataclass(frozen=True)
class Geometry:
    shape: tuple[int, int, int]
    spacing: tuple[float, float, float]
    origin: tuple[float, float, float]
    direction: tuple[float, ...]
    coordinate_system: str
    pixel_type: str
    source: str

    def as_manifest(self) -> dict[str, Any]:
        return {
            "shape": list(self.shape),
            "spacing": list(self.spacing),
            "origin": list(self.origin),
            "direction": list(self.direction),
            "coordinate_system": self.coordinate_system,
            "pixel_type": self.pixel_type,
        }


def infer_format(path: Path) -> str:
    lower = path.name.lower()
    if path.is_dir():
        return "dicom_series"
    if lower.endswith((".nii", ".nii.gz")):
        return "nifti"
    if lower.endswith((".mhd", ".mha")):
        return "metaimage"
    if lower.endswith(".raw"):
        return "raw_binary"
    return "other"


def inspect_image(path: Path, format_name: str | None = None) -> tuple[Geometry, dict[str, Any]]:
    selected_format = format_name or infer_format(path)
    if selected_format == "dicom_series":
        geometry, details = inspect_dicom_series(path)
    elif selected_format == "nifti":
        geometry, details = inspect_nifti(path)
    elif selected_format == "metaimage":
        geometry, details = inspect_metaimage(path)
    else:
        raise ValidationError(f"image format requires explicit sidecar support and is not inspectable yet: {selected_format}")
    return geometry, {"format": selected_format, **details}


def inspect_nifti(path: Path) -> tuple[Geometry, dict[str, Any]]:
    image = nib.load(str(path))
    if len(image.shape) != 3:
        raise ValidationError(f"only 3D NIfTI is supported for annotation: {path} has shape {image.shape}")
    affine = np.asarray(image.affine, dtype=float)
    axes = affine[:3, :3]
    spacing = np.linalg.norm(axes, axis=0)
    if np.any(spacing <= 0):
        raise ValidationError(f"NIfTI has invalid spacing: {path}")
    direction = axes / spacing
    geometry = Geometry(
        shape=tuple(int(value) for value in image.shape),
        spacing=tuple(float(value) for value in spacing),
        origin=tuple(float(value) for value in affine[:3, 3]),
        direction=tuple(float(value) for value in direction.reshape(-1)),
        coordinate_system="RAS",
        pixel_type=str(image.get_data_dtype()),
        source="header",
    )
    return geometry, {
        "hash": prefixed_sha256(path),
        "hash_scope": "file",
        "reader": {"name": "nibabel", "version": nib.__version__},
    }


def _dicom_headers(root: Path) -> list[Any]:
    headers = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        try:
            dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=False)
        except Exception:
            continue
        if hasattr(dataset, "Rows") and hasattr(dataset, "Columns"):
            headers.append((path, dataset))
    if not headers:
        raise ValidationError(f"no readable DICOM image slices found: {root}")
    return headers


def inspect_dicom_series(root: Path) -> tuple[Geometry, dict[str, Any]]:
    headers = _dicom_headers(root)
    series_uids = {str(dataset.get("SeriesInstanceUID", "")) for _, dataset in headers}
    if "" in series_uids or len(series_uids) != 1:
        raise ValidationError(
            f"one image_set must contain exactly one DICOM SeriesInstanceUID; found {sorted(series_uids)} in {root}"
        )

    first = headers[0][1]
    sensitive_keywords = (
        "PatientBirthDate",
        "PatientAddress",
        "PatientTelephoneNumbers",
        "OtherPatientIDs",
        "OtherPatientNames",
        "ReferringPhysicianName",
        "PerformingPhysicianName",
        "OperatorsName",
        "InstitutionName",
        "InstitutionAddress",
        "AccessionNumber",
    )
    sensitive_tags_present = sorted(
        keyword
        for keyword in sensitive_keywords
        if any(str(dataset.get(keyword, "")).strip() for _, dataset in headers)
    )
    patient_identity_removed = sorted(
        {str(dataset.get("PatientIdentityRemoved", "")).strip() for _, dataset in headers}
    )
    burned_in_annotation = sorted(
        {str(dataset.get("BurnedInAnnotation", "")).strip() for _, dataset in headers}
    )
    rows = int(first.Rows)
    columns = int(first.Columns)
    pixel_spacing = [float(value) for value in first.PixelSpacing]
    orientation = np.asarray([float(value) for value in first.ImageOrientationPatient], dtype=float)
    axis_x = orientation[:3]
    axis_y = orientation[3:]
    if not np.isclose(np.linalg.norm(axis_x), 1.0, atol=1e-5) or not np.isclose(
        np.linalg.norm(axis_y), 1.0, atol=1e-5
    ):
        raise ValidationError(f"DICOM direction cosines are not unit length: {root}")
    if not np.isclose(float(np.dot(axis_x, axis_y)), 0.0, atol=1e-5):
        raise ValidationError(f"DICOM row and column directions are not orthogonal: {root}")
    axis_x = axis_x / np.linalg.norm(axis_x)
    axis_y = axis_y / np.linalg.norm(axis_y)
    axis_z = np.cross(axis_x, axis_y)
    axis_z = axis_z / np.linalg.norm(axis_z)
    positions = []
    for path, dataset in headers:
        if int(dataset.Rows) != rows or int(dataset.Columns) != columns:
            raise ValidationError(f"DICOM series has inconsistent matrix size: {path}")
        current_orientation = np.asarray([float(value) for value in dataset.ImageOrientationPatient], dtype=float)
        if not np.allclose(current_orientation, orientation, atol=1e-5):
            raise ValidationError(f"DICOM series has inconsistent orientation: {path}")
        position = np.asarray([float(value) for value in dataset.ImagePositionPatient], dtype=float)
        positions.append((float(np.dot(position, axis_z)), position, path))
    positions.sort(key=lambda item: item[0])
    first_scalar, first_position, _ = positions[0]
    for scalar, position, path in positions:
        expected_position = first_position + axis_z * (scalar - first_scalar)
        residual = float(np.linalg.norm(position - expected_position))
        if residual > 1e-3:
            raise ValidationError(
                f"DICOM series uses a sheared or tilted slice grid unsupported by the current buffer bridge: "
                f"{path} residual={residual:.6f} mm"
            )

    if len(positions) > 1:
        gaps = np.diff([item[0] for item in positions])
        slice_spacing = float(np.median(np.abs(gaps)))
        if slice_spacing <= 0 or not np.allclose(np.abs(gaps), slice_spacing, rtol=1e-3, atol=1e-3):
            raise ValidationError(f"DICOM series has duplicate or non-uniform slice positions: {root}")
    else:
        slice_spacing = float(first.get("SpacingBetweenSlices", first.get("SliceThickness", 1.0)))

    direction = np.column_stack([axis_x, axis_y, axis_z])
    series_uid = next(iter(series_uids))
    geometry = Geometry(
        shape=(columns, rows, len(positions)),
        spacing=(pixel_spacing[1], pixel_spacing[0], slice_spacing),
        origin=tuple(float(value) for value in positions[0][1]),
        direction=tuple(float(value) for value in direction.reshape(-1)),
        coordinate_system="LPS",
        pixel_type=f"{getattr(first, 'PixelRepresentation', 0)}:{getattr(first, 'BitsAllocated', 'unknown')}",
        source="dicom",
    )
    return geometry, {
        "hash": hash_directory(root),
        "hash_scope": "bundle_manifest",
        "reader": {"name": "pydicom", "version": pydicom.__version__},
        "dicom_series_uid_sha256": "sha256:" + hashlib.sha256(series_uid.encode("utf-8")).hexdigest(),
        "series_description": str(first.get("SeriesDescription", "")),
        "study_instance_uid_sha256": "sha256:"
        + hashlib.sha256(str(first.get("StudyInstanceUID", "")).encode("utf-8")).hexdigest(),
        "slice_count": len(positions),
        "deidentification_scan": {
            "sensitive_tags_present": sensitive_tags_present,
            "patient_identity_removed_values": patient_identity_removed,
            "burned_in_annotation_values": burned_in_annotation,
        },
    }


def inspect_metaimage(path: Path) -> tuple[Geometry, dict[str, Any]]:
    try:
        import SimpleITK as sitk
    except ImportError as error:
        raise ConfigurationError("MetaImage support requires `pip install -e '.[metaimage]'`") from error
    image = sitk.ReadImage(str(path))
    if image.GetDimension() != 3:
        raise ValidationError(f"only 3D MetaImage is supported: {path}")
    geometry = Geometry(
        shape=tuple(int(value) for value in image.GetSize()),
        spacing=tuple(float(value) for value in image.GetSpacing()),
        origin=tuple(float(value) for value in image.GetOrigin()),
        direction=tuple(float(value) for value in image.GetDirection()),
        coordinate_system="LPS",
        pixel_type=image.GetPixelIDTypeAsString(),
        source="header",
    )
    companions = []
    if path.suffix.lower() == ".mhd":
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("ElementDataFile") and "=" in line:
                companion = path.parent / line.split("=", 1)[1].strip()
                if companion.exists():
                    companions.append(str(companion))
    return geometry, {
        "hash": prefixed_sha256(path),
        "hash_scope": "file",
        "reader": {"name": "SimpleITK", "version": sitk.Version_VersionString()},
        "companion_paths": companions,
    }


def read_mask(path: Path) -> tuple[np.ndarray, Geometry]:
    selected_format = infer_format(path)
    if selected_format == "nifti":
        geometry, _ = inspect_nifti(path)
        array = np.asanyarray(nib.load(str(path)).dataobj)
    elif selected_format == "metaimage":
        try:
            import SimpleITK as sitk
        except ImportError as error:
            raise ConfigurationError("MetaImage support requires `pip install -e '.[metaimage]'`") from error
        geometry, _ = inspect_metaimage(path)
        array = sitk.GetArrayFromImage(sitk.ReadImage(str(path))).transpose(2, 1, 0)
    else:
        raise ValidationError(f"unsupported mask format: {path}")
    if array.ndim != 3:
        raise ValidationError(f"mask must be 3D: {path}")
    return np.asarray(array), geometry


def geometry_matches(left: Geometry, right: Geometry, *, atol: float = 1e-4) -> tuple[bool, list[str]]:
    reasons = []
    if left.shape != right.shape:
        reasons.append(f"shape differs: {left.shape} != {right.shape}")
    if left.coordinate_system in {"LPS", "RAS"} and right.coordinate_system in {"LPS", "RAS"}:
        if not np.allclose(affine_from_geometry(left), affine_from_geometry(right), atol=atol, rtol=0):
            reasons.append("physical affine differs")
    else:
        if left.coordinate_system != right.coordinate_system:
            reasons.append(f"coordinate system differs: {left.coordinate_system} != {right.coordinate_system}")
        for name, a, b in (
            ("spacing", left.spacing, right.spacing),
            ("origin", left.origin, right.origin),
            ("direction", left.direction, right.direction),
        ):
            if not np.allclose(a, b, atol=atol, rtol=0):
                reasons.append(f"{name} differs")
    return not reasons, reasons


def geometry_from_manifest(value: dict[str, Any]) -> Geometry:
    return Geometry(
        shape=tuple(int(item) for item in value["shape"]),
        spacing=tuple(float(item) for item in value["spacing"]),
        origin=tuple(float(item) for item in value["origin"]),
        direction=tuple(float(item) for item in value["direction"]),
        coordinate_system=value.get("coordinate_system", "unknown"),
        pixel_type=value.get("pixel_type", "unknown"),
        source="manifest",
    )


def affine_from_geometry(geometry: Geometry) -> np.ndarray:
    direction = np.asarray(geometry.direction, dtype=float).reshape(3, 3)
    affine = np.eye(4, dtype=float)
    affine[:3, :3] = direction * np.asarray(geometry.spacing, dtype=float)
    affine[:3, 3] = np.asarray(geometry.origin, dtype=float)
    if geometry.coordinate_system == "LPS":
        lps_to_ras = np.diag([-1.0, -1.0, 1.0, 1.0])
        affine = lps_to_ras @ affine
    elif geometry.coordinate_system != "RAS":
        raise ValidationError(f"cannot write physical-space NIfTI from coordinate system {geometry.coordinate_system}")
    return affine


def write_mask_nifti(path: Path, array_xyz: np.ndarray, geometry: Geometry) -> None:
    if tuple(array_xyz.shape) != geometry.shape:
        raise ValidationError(f"output mask shape {array_xyz.shape} does not match image shape {geometry.shape}")
    path.parent.mkdir(parents=True, exist_ok=True)
    image = nib.Nifti1Image(np.asarray(array_xyz, dtype=np.uint8), affine_from_geometry(geometry))
    image.set_data_dtype(np.uint8)
    nib.save(image, str(path))


@dataclass(frozen=True)
class BufferMapping:
    axes: tuple[int, int, int]
    flips: tuple[bool, bool, bool]
    status: str
    evidence_id: str

    @classmethod
    def from_config(cls, value: dict[str, Any]) -> "BufferMapping":
        axes = tuple(int(item) for item in value.get("platform_to_mimics_axes", []))
        flips = tuple(bool(item) for item in value.get("platform_to_mimics_flips", []))
        if sorted(axes) != [0, 1, 2] or len(flips) != 3:
            raise ConfigurationError("buffer mapping requires a permutation of [0,1,2] and three flip flags")
        return cls(
            axes=axes,
            flips=flips,
            status=str(value.get("status", "unverified")),
            evidence_id=str(value.get("evidence_id", "")),
        )

    def require_verified(self) -> None:
        if self.status != "verified" or not self.evidence_id:
            raise ConfigurationError(
                "Mimics buffer mapping is not verified; execute P05 and set status=verified with evidence_id"
            )

    def platform_to_mimics(self, array: np.ndarray) -> np.ndarray:
        transformed = np.transpose(array, self.axes)
        for axis, should_flip in enumerate(self.flips):
            if should_flip:
                transformed = np.flip(transformed, axis=axis)
        return np.ascontiguousarray(transformed)

    def mimics_to_platform(self, array: np.ndarray) -> np.ndarray:
        transformed = array
        for axis, should_flip in enumerate(self.flips):
            if should_flip:
                transformed = np.flip(transformed, axis=axis)
        inverse_axes = tuple(int(value) for value in np.argsort(self.axes))
        return np.ascontiguousarray(np.transpose(transformed, inverse_axes))


def voxel_count(shape: tuple[int, int, int] | list[int]) -> int:
    return math.prod(int(value) for value in shape)
