from __future__ import annotations

from pathlib import Path
from typing import Any

from segplatform.common import load_data, utc_now
from segplatform.registry import FileRegistry


def _submission_blocks_next(record: dict[str, Any]) -> bool:
    package_path = record.get("package_path")
    if not package_path:
        return False
    package_root = Path(str(package_path))
    submission = package_root / "submissions" / record["review_id"] / "submission_manifest.json"
    if not submission.is_file():
        return False
    report = package_root / "reports" / "review_report.json"
    if not report.is_file():
        return True
    try:
        report_data = load_data(report)
    except Exception:
        return True
    if report_data.get("status") != "failed":
        return True
    return report.stat().st_mtime < submission.stat().st_mtime


def next_review(
    registry_root: Path,
    *,
    assignee: str | None = None,
    include_statuses: set[str] | None = None,
    exclude_review_id: str | None = None,
) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    statuses = include_statuses or {"ready", "in_progress", "needs_review"}
    candidates = []
    for record in registry.list("reviews"):
        if exclude_review_id and record.get("review_id") == exclude_review_id:
            continue
        if assignee and record.get("assignee") != assignee:
            continue
        if record.get("status") not in statuses:
            continue
        if _submission_blocks_next(record):
            continue
        if not record.get("package_path"):
            continue
        candidates.append(record)
    candidates.sort(key=lambda item: (item.get("created_at", ""), item["review_id"]))
    if not candidates:
        return {"status": "empty", "review": None}
    record = candidates[0]
    return {
        "status": "found",
        "review_id": record["review_id"],
        "case_id": record["case_id"],
        "package_path": record["package_path"],
        "review": record,
    }


def mark_review_started(
    registry_root: Path,
    review_id: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    record = registry.get("reviews", review_id)
    record["status"] = "in_progress"
    for target in record["targets"]:
        if target["status"] == "ready":
            target["status"] = "in_progress"
    record.setdefault("events", []).append(
        {
            "at": utc_now(),
            "action": "open_started",
            "actor": actor or record.get("assignee") or "mimics_review_console",
            "target_ids": [target["target_id"] for target in record["targets"]],
        }
    )
    registry.put("reviews", record, allow_update=True)
    return {"status": "started", "review_id": review_id}
