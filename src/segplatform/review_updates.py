from __future__ import annotations

import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

from segplatform.common import canonical_id, load_data, prefixed_sha256, utc_now, write_json
from segplatform.errors import ValidationError
from segplatform.registry import FileRegistry
from segplatform.vocabulary import AnatomyVocabulary


def _source_package_for_case(registry: FileRegistry, case_id: str, source_cases_root: Path | None) -> Path:
    if source_cases_root is not None:
        candidate = source_cases_root.resolve() / case_id
        if (candidate / "manifest.json").is_file():
            return candidate
    reviews = [
        review
        for review in registry.list("reviews")
        if review.get("case_id") == case_id and review.get("package_path")
    ]
    reviews.sort(key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item["review_id"]), reverse=True)
    for review in reviews:
        package = Path(str(review["package_path"])).resolve()
        if (package / "manifest.json").is_file():
            return package
    raise ValidationError(f"cannot find source package for case {case_id}")


def _active_labels_for_image(registry: FileRegistry, case_id: str, image_id: str) -> list[dict[str, Any]]:
    return [
        label
        for label in registry.list("labels")
        if label.get("case_id") == case_id
        and label.get("image_id") == image_id
        and label.get("artifact_lifecycle") == "active"
    ]


def _best_base_label(registry: FileRegistry, case_id: str, image_id: str) -> dict[str, Any] | None:
    labels = _active_labels_for_image(registry, case_id, image_id)
    if not labels:
        return None
    labels.sort(key=lambda item: (len(item.get("segments", [])), item["label_id"]), reverse=True)
    return labels[0]


def _reset_workspace(case_root: Path) -> None:
    for name in ("working", "submissions", "reports", "provenance"):
        path = case_root / name
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(exist_ok=True)


def _copy_base_masks(case_root: Path, image_id: str, base_label: dict[str, Any]) -> list[dict[str, Any]]:
    labels_root = case_root / "labels" / image_id / "masks"
    if labels_root.exists():
        shutil.rmtree(labels_root)
    labels_root.mkdir(parents=True, exist_ok=True)
    initial_labels = []
    for segment in base_label.get("segments", []):
        organ = segment["organ"]
        source = Path(segment["path"])
        destination = labels_root / f"{organ}.nii.gz"
        shutil.copy2(source, destination)
        initial_labels.append(
            {
                "image_id": image_id,
                "organ": organ,
                "path": destination.relative_to(case_root).as_posix(),
                "sha256": prefixed_sha256(destination),
                "lifecycle_status": segment["lifecycle_status"],
                "label_id": base_label["label_id"],
                "label_bundle_sha256": base_label["hash"],
                "usage_constraints": base_label.get(
                    "usage_constraints",
                    {
                        "model_training": "needs_policy",
                        "commercial_use": "needs_policy",
                        "redistribution": "needs_policy",
                    },
                ),
            }
        )
    return initial_labels


def create_followup_reviews(
    registry_root: Path,
    output_root: Path,
    *,
    organs: list[str],
    assignee: str | None = None,
    case_ids: list[str] | None = None,
    source_cases_root: Path | None = None,
    review_suffix: str = "followup",
    allow_no_base: bool = False,
    overwrite: bool = False,
    image_ids_by_case: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Create new review packages for incremental organs or re-review tasks."""

    registry = FileRegistry(registry_root)
    vocabulary = AnatomyVocabulary()
    target_organs = vocabulary.require_all(organs)
    selected_case_ids = set(case_ids or [])
    cases = [
        case
        for case in registry.list("cases")
        if not selected_case_ids or case["case_id"] in selected_case_ids
    ]
    output_cases_root = output_root.resolve() / "cases"
    output_cases_root.mkdir(parents=True, exist_ok=True)
    results = []

    for case in cases:
        case_id = case["case_id"]
        source_package = _source_package_for_case(registry, case_id, source_cases_root)
        review_id = canonical_id(f"review_{case_id}_{review_suffix}", "review_id")
        package_id = canonical_id(f"pkg_{case_id}_{review_suffix}", "package_id")
        destination = output_cases_root / f"{case_id}-{review_suffix}"
        if destination.exists():
            if not overwrite:
                results.append({"case_id": case_id, "status": "skipped", "reason": "package_exists", "package_path": str(destination)})
                continue
            shutil.rmtree(destination)
        if (registry.root / "reviews" / f"{review_id}.json").exists() and not overwrite:
            results.append({"case_id": case_id, "status": "skipped", "reason": "review_exists", "review_id": review_id})
            continue

        shutil.copytree(source_package, destination)
        _reset_workspace(destination)
        manifest = load_data(destination / "manifest.json")
        targets = []
        initial_labels = []
        base_by_target = {}
        selected_image_ids = image_ids_by_case.get(case_id) if image_ids_by_case else None
        for image_id in case["image_ids"]:
            if selected_image_ids is not None and image_id not in selected_image_ids:
                continue
            base_label = _best_base_label(registry, case_id, image_id)
            target_id = canonical_id(f"target_{image_id}_{review_suffix}", "target_id")
            target = {
                "target_id": target_id,
                "image_id": image_id,
                "organs": target_organs,
            }
            if base_label:
                target["base_label_id"] = base_label["label_id"]
                target["base_label_sha256"] = base_label["hash"]
                initial_labels.extend(_copy_base_masks(destination, image_id, base_label))
                base_by_target[target_id] = base_label["label_id"]
            elif not allow_no_base:
                continue
            targets.append(target)
        if not targets:
            shutil.rmtree(destination)
            results.append({"case_id": case_id, "status": "skipped", "reason": "no_base_label"})
            continue

        manifest["package_id"] = package_id
        manifest["created_at"] = utc_now()
        manifest["initial_labels"] = initial_labels
        manifest["review"] = {
            "review_id": review_id,
            "tool": manifest.get("review", {}).get("tool", "mimics"),
            "status": "ready",
            "assignee": assignee if assignee is not None else manifest.get("review", {}).get("assignee"),
            "targets": targets,
        }
        write_json(destination / "manifest.json", manifest)

        review_record = {
            "schema_version": "review_task.v1",
            "review_id": review_id,
            "package_id": package_id,
            "case_id": case_id,
            "tool": manifest["review"]["tool"],
            "status": "ready",
            "assignee": manifest["review"].get("assignee"),
            "package_path": str(destination.resolve()),
            "created_at": utc_now(),
            "targets": [{**target, "status": "ready"} for target in targets],
            "events": [
                {
                    "at": utc_now(),
                    "action": "followup_created",
                    "actor": "platform",
                    "detail": "base_labels=" + ",".join(f"{key}:{value}" for key, value in sorted(base_by_target.items())),
                }
            ],
        }
        if (registry.root / "reviews" / f"{review_id}.json").exists() and overwrite:
            registry.put("reviews", review_record, allow_update=True)
        else:
            registry.put("reviews", review_record)
        results.append(
            {
                "case_id": case_id,
                "status": "created",
                "review_id": review_id,
                "package_path": str(destination.resolve()),
                "targets": [target["target_id"] for target in targets],
            }
        )

    return {
        "status": "created",
        "review_count": len([item for item in results if item["status"] == "created"]),
        "results": results,
    }


def _finding_organs(item: dict[str, Any]) -> list[str]:
    organs = []
    if isinstance(item.get("missing_organs"), list):
        organs.extend(str(organ) for organ in item["missing_organs"])
    if isinstance(item.get("organs"), list):
        organs.extend(str(organ) for organ in item["organs"])
    for key in ("ambiguous", "rejected_status"):
        values = item.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict) and value.get("organ"):
                    organs.append(str(value["organ"]))
    if item.get("organ"):
        organs.append(str(item["organ"]))
    return organs


def _load_finding_items(path: Path) -> list[dict[str, Any]]:
    payload = load_data(path)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("skipped", "findings", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    raise ValidationError("finding file must be a list or contain skipped/findings/results")


def create_followup_reviews_from_findings(
    registry_root: Path,
    output_root: Path,
    finding_path: Path,
    *,
    assignee: str | None = None,
    source_cases_root: Path | None = None,
    review_suffix: str = "finding",
    allow_no_base: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create follow-up reviews from snapshot/QC finding reports."""

    vocabulary = AnatomyVocabulary()
    groups: dict[tuple[str, ...], dict[str, Any]] = {}
    unsupported = []
    for item in _load_finding_items(finding_path):
        case_id = item.get("case_id")
        if not case_id:
            unsupported.append({"finding": item, "reason": "missing_case_id"})
            continue
        organs = vocabulary.require_all(_finding_organs(item))
        if not organs:
            unsupported.append({"finding": item, "reason": "no_actionable_organs"})
            continue
        key = tuple(sorted(organs))
        group = groups.setdefault(key, {"case_ids": set(), "image_ids_by_case": defaultdict(set)})
        canonical_case_id = canonical_id(str(case_id), "case_id")
        group["case_ids"].add(canonical_case_id)
        image_id = item.get("image_id")
        if image_id:
            group["image_ids_by_case"][canonical_case_id].add(canonical_id(str(image_id), "image_id"))

    results = []
    created = 0
    for index, (organs, group) in enumerate(sorted(groups.items()), start=1):
        suffix = canonical_id(f"{review_suffix}_{index:02d}", "review_suffix")
        image_ids_by_case = {
            case_id: set(image_ids)
            for case_id, image_ids in group["image_ids_by_case"].items()
            if image_ids
        }
        result = create_followup_reviews(
            registry_root,
            output_root,
            organs=list(organs),
            assignee=assignee,
            case_ids=sorted(group["case_ids"]),
            source_cases_root=source_cases_root,
            review_suffix=suffix,
            allow_no_base=allow_no_base,
            overwrite=overwrite,
            image_ids_by_case=image_ids_by_case or None,
        )
        created += int(result.get("review_count", 0))
        results.append({"organs": list(organs), **result})
    return {
        "status": "created",
        "review_count": created,
        "groups": results,
        "unsupported": unsupported,
    }
