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
    claim_unassigned: bool = False,
) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    statuses = include_statuses or {"ready", "in_progress", "needs_review"}
    candidates = []
    for record in registry.list("reviews"):
        if exclude_review_id and record.get("review_id") == exclude_review_id:
            continue
        record_assignee = record.get("assignee")
        if assignee and record_assignee != assignee:
            if not (claim_unassigned and record_assignee in (None, "")):
                continue
        elif not assignee and claim_unassigned:
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
    if assignee and claim_unassigned and record.get("assignee") in (None, ""):
        record["assignee"] = assignee
        record.setdefault("events", []).append(
            {
                "at": utc_now(),
                "action": "claimed",
                "actor": assignee,
                "detail": "claimed from unassigned queue",
            }
        )
        registry.put("reviews", record, allow_update=True)
    return {
        "status": "found",
        "review_id": record["review_id"],
        "case_id": record["case_id"],
        "package_path": record["package_path"],
        "review": record,
    }


def assign_review(
    registry_root: Path,
    review_id: str,
    *,
    assignee: str | None,
    actor: str | None = None,
) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    record = registry.get("reviews", review_id)
    previous = record.get("assignee")
    record["assignee"] = assignee
    record.setdefault("events", []).append(
        {
            "at": utc_now(),
            "action": "assigned" if assignee else "assignment_cleared",
            "actor": actor or "offline_operator",
            "detail": f"{previous!r} -> {assignee!r}",
            "target_ids": [target["target_id"] for target in record.get("targets", [])],
        }
    )
    registry.put("reviews", record, allow_update=True)
    return {"status": "assigned" if assignee else "unassigned", "review_id": review_id, "assignee": assignee}


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


def defer_review(
    registry_root: Path,
    review_id: str,
    *,
    actor: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    record = registry.get("reviews", review_id)
    record["status"] = "deferred"
    for target in record["targets"]:
        if target["status"] in {"ready", "in_progress", "needs_review"}:
            target["status"] = "deferred"
    event = {
        "at": utc_now(),
        "action": "deferred",
        "actor": actor or record.get("assignee") or "offline_operator",
        "target_ids": [target["target_id"] for target in record["targets"]],
    }
    if reason:
        event["detail"] = reason
    record.setdefault("events", []).append(event)
    registry.put("reviews", record, allow_update=True)
    return {"status": "deferred", "review_id": review_id}


def reactivate_review(
    registry_root: Path,
    review_id: str,
    *,
    actor: str | None = None,
) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    record = registry.get("reviews", review_id)
    if record.get("status") != "deferred":
        return {"status": "unchanged", "review_id": review_id, "current_status": record.get("status")}
    record["status"] = "ready"
    for target in record["targets"]:
        if target["status"] == "deferred":
            target["status"] = "ready"
    record.setdefault("events", []).append(
        {
            "at": utc_now(),
            "action": "reactivated",
            "actor": actor or record.get("assignee") or "offline_operator",
            "target_ids": [target["target_id"] for target in record["targets"]],
        }
    )
    registry.put("reviews", record, allow_update=True)
    return {"status": "ready", "review_id": review_id}


def review_stats(registry_root: Path) -> dict[str, Any]:
    registry = FileRegistry(registry_root)
    by_status: dict[str, int] = {}
    by_assignee: dict[str, dict[str, int]] = {}
    submitted_pending = 0
    total = 0
    for record in registry.list("reviews"):
        total += 1
        status = str(record.get("status", "unknown"))
        assignee = str(record.get("assignee") or "unassigned")
        by_status[status] = by_status.get(status, 0) + 1
        assignee_counts = by_assignee.setdefault(assignee, {})
        assignee_counts[status] = assignee_counts.get(status, 0) + 1
        if _submission_blocks_next(record):
            submitted_pending += 1
    return {
        "status": "ok",
        "total_reviews": total,
        "by_status": dict(sorted(by_status.items())),
        "by_assignee": {key: dict(sorted(value.items())) for key, value in sorted(by_assignee.items())},
        "submitted_pending_or_completed": submitted_pending,
    }
