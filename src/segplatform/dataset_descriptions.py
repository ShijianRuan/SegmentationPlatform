from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from segplatform.common import canonical_id, load_data, utc_now, write_json, write_yaml
from segplatform.errors import ValidationError
from segplatform.imaging import infer_format
from segplatform.vocabulary import AnatomyVocabulary


class _FormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        raise ValidationError(f"dataset description template references missing group: {key}")


def _render(template: str, values: dict[str, str]) -> str:
    return template.format_map(_FormatDict(values))


def _split_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_mapping(value: Any) -> dict[str, int]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return {str(key): int(raw) for key, raw in value.items()}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError as error:
        raise ValidationError(f"label_map must be a JSON object or mapping: {value}") from error
    if not isinstance(parsed, dict):
        raise ValidationError("label_map must parse to an object")
    return {str(key): int(raw) for key, raw in parsed.items()}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValidationError(f"dataset description table does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _case_defaults(dataset_id: str, groups: dict[str, str], rule: dict[str, Any]) -> dict[str, str]:
    case_id = canonical_id(_render(str(rule.get("case_id", "case_{case}")), groups), "case_id")
    study_id = canonical_id(_render(str(rule.get("study_id", "study_{case}")), groups), "study_id")
    leakage = str(rule.get("leakage_group_id", "subject_{case}"))
    leakage_group_id = canonical_id(_render(leakage, groups), "leakage_group_id")
    return {
        "case_id": case_id,
        "study_id": study_id,
        "leakage_group_id": leakage_group_id,
        "leakage_group_basis": str(rule.get("leakage_group_basis", f"{dataset_id}_description")),
        "leakage_group_confidence": str(rule.get("leakage_group_confidence", "medium")),
    }


def _empty_case(metadata: dict[str, str]) -> dict[str, Any]:
    return {
        **metadata,
        "image_sets": {},
        "initial_labels": [],
    }


def _table_path(root: Path, description_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    candidate = root / path
    if candidate.exists():
        return candidate.resolve()
    return (description_path.parent / path).resolve()


def _add_image(
    cases: dict[str, dict[str, Any]],
    *,
    metadata: dict[str, str],
    image_id: str,
    path: Path,
    format_name: str | None,
    modality: str,
    source_type: str,
    import_batch: str,
    target_organs: list[str],
    source_layout: dict[str, Any] | None = None,
) -> None:
    case = cases.setdefault(metadata["case_id"], _empty_case(metadata))
    if case["study_id"] != metadata["study_id"]:
        raise ValidationError(f"case {metadata['case_id']} has conflicting study_id values")
    canonical_image_id = canonical_id(image_id, "image_id")
    if canonical_image_id in case["image_sets"]:
        raise ValidationError(f"duplicate image_id in dataset description: {canonical_image_id}")
    case["image_sets"][canonical_image_id] = {
        "image_id": canonical_image_id,
        "modality": modality,
        "format": format_name or infer_format(path),
        "source": str(path.resolve()),
        "source_type": source_type,
        "import_batch": import_batch,
        "source_layout": source_layout or {},
        "target_organs": target_organs,
    }


def _add_label(
    cases: dict[str, dict[str, Any]],
    *,
    case_id: str,
    image_id: str,
    path: Path,
    organ: str | None,
    label_map: dict[str, int],
    lifecycle_status: str,
    source_type: str | None = None,
    generator_id: str | None = None,
) -> None:
    canonical_case_id = canonical_id(case_id, "case_id")
    canonical_image_id = canonical_id(image_id, "image_id")
    if canonical_case_id not in cases:
        raise ValidationError(f"label references unknown case_id: {canonical_case_id}")
    if canonical_image_id not in cases[canonical_case_id]["image_sets"]:
        raise ValidationError(f"label references unknown image_id: {canonical_image_id}")
    entry: dict[str, Any] = {
        "image_id": canonical_image_id,
        "path": str(path.resolve()),
        "lifecycle_status": lifecycle_status,
    }
    if organ:
        entry["organ"] = organ
    elif label_map:
        entry["label_map"] = label_map
    else:
        raise ValidationError(f"label entry requires organ or label_map: {path}")
    if source_type:
        entry["source_type"] = source_type
    if generator_id:
        entry["generator_id"] = generator_id
    cases[canonical_case_id]["initial_labels"].append(entry)


def _discover_regex(
    description: dict[str, Any],
    description_path: Path,
    root: Path,
    cases: dict[str, dict[str, Any]],
) -> None:
    defaults = description.get("defaults", {})
    dataset_id = str(description.get("dataset_id", "dataset"))
    source_type = str(defaults.get("source_type", "dataset_description"))
    import_batch = str(defaults.get("import_batch", dataset_id))
    default_modality = str(defaults.get("modality", "UNKNOWN"))
    vocabulary = AnatomyVocabulary()
    default_organs = vocabulary.require_all(_split_list(defaults.get("organs")))

    discovery = description.get("discovery", {})
    files = sorted(path for path in root.rglob("*") if path.is_file())
    case_by_key: dict[tuple[str, str], str] = {}

    for rule in discovery.get("images", []):
        pattern = re.compile(str(rule["regex"]))
        for path in files:
            relative = path.relative_to(root).as_posix()
            match = pattern.fullmatch(relative)
            if not match:
                continue
            groups = {key: value for key, value in match.groupdict().items() if value is not None}
            if "case" not in groups:
                groups["case"] = Path(relative).parent.as_posix().replace("/", "_") or Path(relative).stem
            metadata = _case_defaults(dataset_id, groups, rule)
            image_id = _render(str(rule.get("image_id", "img_{case}")), groups)
            target_organs = vocabulary.require_all(_split_list(rule.get("target_organs")) or default_organs)
            _add_image(
                cases,
                metadata=metadata,
                image_id=image_id,
                path=path,
                format_name=rule.get("format"),
                modality=str(rule.get("modality", default_modality)),
                source_type=source_type,
                import_batch=import_batch,
                target_organs=target_organs,
                source_layout={"regex": str(rule["regex"]), "relative_path": relative},
            )
            case_by_key[(groups["case"], image_id)] = metadata["case_id"]

    for rule in discovery.get("labels", []):
        pattern = re.compile(str(rule["regex"]))
        label_type = str(rule.get("type", "per_organ"))
        lifecycle = str(rule.get("lifecycle_status", defaults.get("label_lifecycle_status", "source_label")))
        for path in files:
            relative = path.relative_to(root).as_posix()
            match = pattern.fullmatch(relative)
            if not match:
                continue
            groups = {key: value for key, value in match.groupdict().items() if value is not None}
            if "case" not in groups:
                raise ValidationError(f"label regex must expose a case group: {rule['regex']}")
            image_id = _render(str(rule.get("image_id", "img_{case}")), groups)
            case_id = case_by_key.get((groups["case"], image_id))
            if case_id is None:
                case_id = canonical_id(_render(str(rule.get("case_id", "case_{case}")), groups), "case_id")
            if label_type == "per_organ":
                organ_template = str(rule.get("organ", "{organ}"))
                organ = vocabulary.normalize(_render(organ_template, groups))
                label_map = {}
            elif label_type == "multilabel":
                organ = None
                label_map = {vocabulary.normalize(name): value for name, value in _parse_mapping(rule.get("label_map")).items()}
            else:
                raise ValidationError(f"unsupported label discovery type: {label_type}")
            _add_label(
                cases,
                case_id=case_id,
                image_id=image_id,
                path=path,
                organ=organ,
                label_map=label_map,
                lifecycle_status=lifecycle,
                source_type=rule.get("source_type"),
                generator_id=rule.get("generator_id"),
            )


def _discover_tables(
    description: dict[str, Any],
    description_path: Path,
    root: Path,
    cases: dict[str, dict[str, Any]],
) -> None:
    tables = description.get("tables", {})
    if not tables:
        return
    defaults = description.get("defaults", {})
    dataset_id = str(description.get("dataset_id", "dataset"))
    source_type = str(defaults.get("source_type", "dataset_description"))
    import_batch = str(defaults.get("import_batch", dataset_id))
    default_modality = str(defaults.get("modality", "UNKNOWN"))
    vocabulary = AnatomyVocabulary()
    default_organs = vocabulary.require_all(_split_list(defaults.get("organs")))

    if tables.get("images"):
        for row in _read_csv_rows(_table_path(root, description_path, str(tables["images"]))):
            groups = defaultdict(str, {key: str(value or "") for key, value in row.items()})
            metadata = {
                "case_id": canonical_id(str(row["case_id"]), "case_id"),
                "study_id": canonical_id(str(row.get("study_id") or row["case_id"]), "study_id"),
                "leakage_group_id": canonical_id(
                    str(row.get("leakage_group_id") or row["case_id"]),
                    "leakage_group_id",
                ),
                "leakage_group_basis": str(row.get("leakage_group_basis") or f"{dataset_id}_table"),
                "leakage_group_confidence": str(row.get("leakage_group_confidence") or "medium"),
            }
            target_organs = vocabulary.require_all(_split_list(row.get("target_organs")) or default_organs)
            image_path = _table_path(root, description_path, _render(str(row["path"]), groups))
            _add_image(
                cases,
                metadata=metadata,
                image_id=str(row["image_id"]),
                path=image_path,
                format_name=row.get("format") or None,
                modality=str(row.get("modality") or default_modality),
                source_type=str(row.get("source_type") or source_type),
                import_batch=str(row.get("import_batch") or import_batch),
                target_organs=target_organs,
                source_layout={"table": str(tables["images"])},
            )

    if tables.get("labels"):
        for row in _read_csv_rows(_table_path(root, description_path, str(tables["labels"]))):
            groups = defaultdict(str, {key: str(value or "") for key, value in row.items()})
            label_path = _table_path(root, description_path, _render(str(row["path"]), groups))
            raw_label_map = _parse_mapping(row.get("label_map"))
            label_map = {vocabulary.normalize(name): value for name, value in raw_label_map.items()}
            organ = vocabulary.normalize(str(row["organ"])) if row.get("organ") else None
            _add_label(
                cases,
                case_id=str(row["case_id"]),
                image_id=str(row["image_id"]),
                path=label_path,
                organ=organ,
                label_map=label_map,
                lifecycle_status=str(row.get("lifecycle_status") or defaults.get("label_lifecycle_status", "source_label")),
                source_type=row.get("source_type") or None,
                generator_id=row.get("generator_id") or None,
            )


def build_requests_from_dataset_description(description_path: Path, output_dir: Path) -> dict[str, Any]:
    description_path = description_path.expanduser().resolve()
    description = load_data(description_path)
    if description.get("schema_version") != "dataset_description.v1":
        raise ValidationError("dataset description schema_version must be dataset_description.v1")

    root = Path(description["root"]).expanduser()
    if not root.is_absolute():
        root = description_path.parent / root
    root = root.resolve()
    if not root.is_dir():
        raise ValidationError(f"dataset description root must be a directory: {root}")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cases: dict[str, dict[str, Any]] = {}
    _discover_regex(description, description_path, root, cases)
    _discover_tables(description, description_path, root, cases)

    defaults = description.get("defaults", {})
    vocabulary = AnatomyVocabulary()
    default_organs = vocabulary.require_all(_split_list(defaults.get("organs")))
    data_governance = {
        "source_zone": str(defaults.get("source_zone", "working")),
        "deidentification_status": str(defaults.get("deidentification_status", "verified")),
        "profile": str(defaults.get("governance_profile", "dataset_description_profile")),
        "profile_version": str(defaults.get("governance_profile_version", "1")),
        "direct_identifiers_allowed": bool(defaults.get("direct_identifiers_allowed", False)),
        "strict_deidentification": bool(defaults.get("strict_deidentification", False)),
    }
    written = []
    for case_id, case in sorted(cases.items()):
        image_sets = []
        targets = []
        for image_id, image in sorted(case["image_sets"].items()):
            target_organs = image.pop("target_organs", []) or default_organs
            if not target_organs:
                raise ValidationError(f"image {image_id} has no target organs")
            image_sets.append(image)
            targets.append(
                {
                    "target_id": canonical_id(f"target_{image_id}", "target_id"),
                    "image_id": image_id,
                    "organs": target_organs,
                }
            )
        request = {
            "schema_version": "case_package_request.v1",
            "package_id": canonical_id(f"pkg_{case_id}", "package_id"),
            "case_id": case_id,
            "study_id": case["study_id"],
            "leakage_group_id": case["leakage_group_id"],
            "leakage_group_basis": case["leakage_group_basis"],
            "leakage_group_confidence": case["leakage_group_confidence"],
            "data_governance": data_governance,
            "image_sets": image_sets,
            "review": {
                "review_id": canonical_id(f"review_{case_id}_v1", "review_id"),
                "tool": str(defaults.get("tool", "mimics")),
                "assignee": defaults.get("assignee"),
                "targets": targets,
            },
            "initial_labels": case["initial_labels"],
        }
        path = output_dir / f"{case_id}.yaml"
        write_yaml(path, request)
        written.append(str(path))

    summary = {
        "schema_version": "case_package_request_batch.v1",
        "created_at": utc_now(),
        "description_path": str(description_path),
        "request_count": len(written),
        "requests": written,
    }
    write_json(output_dir / "request_batch_summary.json", summary)
    return summary
