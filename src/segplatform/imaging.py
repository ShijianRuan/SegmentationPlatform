from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, MRImageStorage, SecondaryCaptureImageStorage, generate_uid

from segplatform.common import hash_file_set, prefixed_sha256
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
    return _inspect_dicom_headers(headers, hash_value=hash_file_set([path for path, _ in headers], root=root))


def inspect_dicom_files(paths: list[Path], *, root: Path) -> tuple[Geometry, dict[str, Any]]:
    headers = []
    for path in sorted(paths):
        try:
            dataset = pydicom.dcmread(str(path), stop_before_pixels=True, force=False)
        except Exception as error:
            raise ValidationError(f"unreadable DICOM file in explicit series: {path}") from error
        if not hasattr(dataset, "Rows") or not hasattr(dataset, "Columns"):
            raise ValidationError(f"explicit DICOM series contains a non-image file: {path}")
        headers.append((path, dataset))
    if not headers:
        raise ValidationError("explicit DICOM series contains no files")
    return _inspect_dicom_headers(headers, hash_value=hash_file_set([path for path, _ in headers], root=root))


def _inspect_dicom_headers(headers: list[Any], *, hash_value: str) -> tuple[Geometry, dict[str, Any]]:
    series_uids = {str(dataset.get("SeriesInstanceUID", "")) for _, dataset in headers}
    if "" in series_uids or len(series_uids) != 1:
        raise ValidationError(
            f"one image_set must contain exactly one DICOM SeriesInstanceUID; found {sorted(series_uids)}"
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
        raise ValidationError("DICOM direction cosines are not unit length")
    if not np.isclose(float(np.dot(axis_x, axis_y)), 0.0, atol=1e-5):
        raise ValidationError("DICOM row and column directions are not orthogonal")
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
            raise ValidationError("DICOM series has duplicate or non-uniform slice positions")
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
        "hash": hash_value,
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


def _metaimage_companions(path: Path) -> list[Path]:
    if path.suffix.lower() != ".mhd":
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    companions: list[Path] = []
    list_mode = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if list_mode:
            companion = path.parent / stripped
            if companion.exists():
                companions.append(companion)
            continue
        if stripped.startswith("ElementDataFile") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            if value.upper() == "LOCAL":
                return []
            if value.upper() == "LIST":
                list_mode = True
                continue
            companion = path.parent / value
            if companion.exists():
                companions.append(companion)
    return companions


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
    companions = _metaimage_companions(path)
    if companions:
        digest = hash_file_set([path, *companions], root=path.parent)
        hash_scope = "bundle_manifest"
    else:
        digest = prefixed_sha256(path)
        hash_scope = "file"
    return geometry, {
        "hash": digest,
        "hash_scope": hash_scope,
        "reader": {"name": "SimpleITK", "version": sitk.Version_VersionString()},
        "companion_paths": [str(path) for path in companions],
    }


def read_image_array(path: Path, format_name: str | None = None) -> tuple[np.ndarray, Geometry]:
    selected_format = format_name or infer_format(path)
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
        raise ValidationError(f"unsupported image format for derived DICOM conversion: {selected_format}")
    if array.ndim != 3:
        raise ValidationError(f"image must be 3D for Mimics derived DICOM conversion: {path}")
    return np.asarray(array), geometry


def _lps_geometry_from_geometry(geometry: Geometry) -> Geometry:
    affine_ras = affine_from_geometry(geometry)
    ras_to_lps = np.diag([-1.0, -1.0, 1.0, 1.0])
    affine_lps = ras_to_lps @ affine_ras
    axes = affine_lps[:3, :3]
    spacing = np.linalg.norm(axes, axis=0)
    if np.any(spacing <= 0):
        raise ValidationError("cannot derive DICOM from image with invalid spacing")
    direction = axes / spacing
    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-5, rtol=0):
        raise ValidationError("cannot derive DICOM from image with sheared or non-orthogonal affine")
    if not np.allclose(np.cross(direction[:, 0], direction[:, 1]), direction[:, 2], atol=1e-5, rtol=0):
        raise ValidationError("cannot derive DICOM from image with unsupported left-handed axis order")
    return Geometry(
        shape=geometry.shape,
        spacing=tuple(float(value) for value in spacing),
        origin=tuple(float(value) for value in affine_lps[:3, 3]),
        direction=tuple(float(value) for value in direction.reshape(-1)),
        coordinate_system="LPS",
        pixel_type=geometry.pixel_type,
        source=geometry.source,
    )


def _dicom_pixel_payload(array: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    if np.iscomplexobj(array):
        raise ValidationError("complex-valued images cannot be converted to derived DICOM")
    values = np.asarray(array)
    if not np.all(np.isfinite(values)):
        raise ValidationError("image contains NaN or Inf values and cannot be converted to derived DICOM")
    min_value = float(np.min(values))
    max_value = float(np.max(values))
    if np.issubdtype(values.dtype, np.integer) and min_value >= -32768 and max_value <= 32767:
        return values.astype(np.int16, copy=False), {
            "bits_allocated": 16,
            "bits_stored": 16,
            "high_bit": 15,
            "pixel_representation": 1,
            "rescale_slope": 1.0,
            "rescale_intercept": 0.0,
            "conversion": "integer_int16",
        }
    if np.issubdtype(values.dtype, np.integer) and min_value >= 0 and max_value <= 65535:
        return values.astype(np.uint16, copy=False), {
            "bits_allocated": 16,
            "bits_stored": 16,
            "high_bit": 15,
            "pixel_representation": 0,
            "rescale_slope": 1.0,
            "rescale_intercept": 0.0,
            "conversion": "integer_uint16",
        }

    if max_value == min_value:
        scaled = np.zeros(values.shape, dtype=np.int16)
        slope = 1.0
        intercept = min_value
    else:
        slope = (max_value - min_value) / 65535.0
        intercept = min_value + 32768.0 * slope
        scaled = np.rint((values - intercept) / slope).clip(-32768, 32767).astype(np.int16)
    return scaled, {
        "bits_allocated": 16,
        "bits_stored": 16,
        "high_bit": 15,
        "pixel_representation": 1,
        "rescale_slope": float(slope),
        "rescale_intercept": float(intercept),
        "conversion": "scaled_int16",
        "source_min": min_value,
        "source_max": max_value,
    }


def write_derived_dicom_series(
    source: Path,
    destination: Path,
    *,
    format_name: str,
    modality: str,
    case_id: str,
    study_id: str,
    series_description: str | None = None,
) -> dict[str, Any]:
    """Write a deidentified single-series DICOM view for Mimics 21 import.

    The source image remains the platform Image Artifact. This derived DICOM is
    a tool-specific working representation for Mimics, because Mimics 21 does
    not expose a confirmed ImageData voxel-write API for arbitrary NIfTI/MHD
    volumes.
    """

    array, geometry = read_image_array(source, format_name)
    lps_geometry = _lps_geometry_from_geometry(geometry)
    pixel_array, pixel_info = _dicom_pixel_payload(array)
    destination.mkdir(parents=True, exist_ok=True)
    for child in destination.iterdir():
        if child.is_file():
            child.unlink()

    modality_value = str(modality or "OT").upper()
    if modality_value == "CT":
        sop_class_uid = CTImageStorage
    elif modality_value == "MR":
        sop_class_uid = MRImageStorage
    else:
        sop_class_uid = SecondaryCaptureImageStorage
    source_hash = prefixed_sha256(source)
    study_uid = generate_uid(entropy_srcs=[source_hash, "study"])
    series_uid = generate_uid(entropy_srcs=[source_hash, "series"])
    frame_uid = generate_uid(entropy_srcs=[source_hash, "frame"])
    direction = np.asarray(lps_geometry.direction, dtype=float).reshape(3, 3)
    spacing = lps_geometry.spacing
    origin = np.asarray(lps_geometry.origin, dtype=float)
    rows = int(lps_geometry.shape[1])
    columns = int(lps_geometry.shape[0])
    slice_count = int(lps_geometry.shape[2])

    for index in range(slice_count):
        file_meta = FileMetaDataset()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        file_meta.MediaStorageSOPClassUID = sop_class_uid
        file_meta.MediaStorageSOPInstanceUID = generate_uid(entropy_srcs=[source_hash, "sop", str(index)])
        dataset = FileDataset(
            str(destination / f"slice_{index + 1:04d}.dcm"),
            {},
            file_meta=file_meta,
            preamble=b"\0" * 128,
        )
        dataset.SOPClassUID = sop_class_uid
        dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        dataset.PatientName = "ANON"
        dataset.PatientID = case_id[:64]
        dataset.PatientIdentityRemoved = "YES"
        dataset.BurnedInAnnotation = "NO"
        dataset.StudyInstanceUID = study_uid
        dataset.SeriesInstanceUID = series_uid
        dataset.FrameOfReferenceUID = frame_uid
        dataset.StudyID = study_id[:16]
        dataset.SeriesNumber = 1
        dataset.InstanceNumber = index + 1
        dataset.Modality = modality_value if modality_value in {"CT", "MR"} else "OT"
        dataset.SeriesDescription = (series_description or f"SP derived from {format_name}")[:64]
        dataset.Rows = rows
        dataset.Columns = columns
        dataset.PixelSpacing = [float(spacing[1]), float(spacing[0])]
        dataset.SliceThickness = float(spacing[2])
        dataset.SpacingBetweenSlices = float(spacing[2])
        dataset.ImageOrientationPatient = [
            *[float(value) for value in direction[:, 0]],
            *[float(value) for value in direction[:, 1]],
        ]
        position = origin + direction[:, 2] * spacing[2] * index
        dataset.ImagePositionPatient = [float(value) for value in position]
        dataset.SliceLocation = float(np.dot(position, direction[:, 2]))
        dataset.SamplesPerPixel = 1
        dataset.PhotometricInterpretation = "MONOCHROME2"
        dataset.BitsAllocated = pixel_info["bits_allocated"]
        dataset.BitsStored = pixel_info["bits_stored"]
        dataset.HighBit = pixel_info["high_bit"]
        dataset.PixelRepresentation = pixel_info["pixel_representation"]
        dataset.RescaleSlope = pixel_info["rescale_slope"]
        dataset.RescaleIntercept = pixel_info["rescale_intercept"]
        dataset.PixelData = np.ascontiguousarray(pixel_array[:, :, index].T).tobytes()
        dataset.save_as(destination / f"slice_{index + 1:04d}.dcm", enforce_file_format=True)

    derived_geometry, derived_inspection = inspect_dicom_series(destination)
    matches, reasons = geometry_matches(geometry, derived_geometry)
    if not matches:
        raise ValidationError("derived DICOM geometry does not match source image: " + "; ".join(reasons))
    return {
        **derived_inspection,
        "derived_geometry": derived_geometry,
        "source_geometry": geometry,
        "pixel_conversion": pixel_info,
        "source_format": format_name,
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
