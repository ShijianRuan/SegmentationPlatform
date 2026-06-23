from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from segplatform.common import utc_now, write_json


def write_run_record(
    registry_root: Path,
    *,
    action: str,
    status: str,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a lightweight audit record for an offline command.

    This is intentionally not a scheduler or DAG engine. It only records what
    was attempted so later implementation can reconstruct batch provenance.
    """

    run_id = f"run_{utc_now().replace(':', '').replace('+', 'Z')}_{uuid.uuid4().hex[:8]}"
    record = {
        "schema_version": "run_record.v1",
        "run_id": run_id,
        "created_at": utc_now(),
        "action": action,
        "status": status,
        "inputs": inputs or {},
        "outputs": outputs or {},
        "result": result or {},
    }
    path = registry_root.resolve() / "_runs" / f"{run_id}.json"
    write_json(path, record)
    return {"run_id": run_id, "run_record_path": str(path), "record": record}
