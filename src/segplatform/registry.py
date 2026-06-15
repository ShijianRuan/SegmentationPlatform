from __future__ import annotations

from pathlib import Path
from typing import Any

from segplatform.common import canonical_id, load_data, utc_now, write_json
from segplatform.errors import ValidationError
from segplatform.schema import validate_schema


SCHEMA_BY_COLLECTION = {
    "cases": "case_manifest.schema.json",
    "images": "image_artifact.schema.json",
    "labels": "label_artifact.schema.json",
    "reviews": "review_task.schema.json",
    "snapshots": "dataset_snapshot.schema.json",
}

ID_FIELD_BY_COLLECTION = {
    "cases": "case_id",
    "images": "image_id",
    "labels": "label_id",
    "reviews": "review_id",
    "snapshots": "snapshot_id",
}


class FileRegistry:
    """Append-only file registry for the offline phase."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for collection in SCHEMA_BY_COLLECTION:
            (self.root / collection).mkdir(exist_ok=True)

    def put(self, collection: str, record: dict[str, Any], *, allow_update: bool = False) -> Path:
        if collection not in SCHEMA_BY_COLLECTION:
            raise ValueError(f"unknown registry collection: {collection}")
        validate_schema(record, SCHEMA_BY_COLLECTION[collection])
        identifier = canonical_id(str(record[ID_FIELD_BY_COLLECTION[collection]]), ID_FIELD_BY_COLLECTION[collection])
        path = self.root / collection / f"{identifier}.json"
        if path.exists() and not allow_update:
            raise ValidationError(f"immutable registry record already exists: {path}")
        if allow_update and path.exists():
            previous = load_data(path)
            record.setdefault("updated_at", utc_now())
            record.setdefault("created_at", previous.get("created_at", utc_now()))
        write_json(path, record)
        return path

    def get(self, collection: str, identifier: str) -> dict[str, Any]:
        path = self.root / collection / f"{canonical_id(identifier)}.json"
        if not path.exists():
            raise ValidationError(f"registry record not found: {collection}/{identifier}")
        return load_data(path)

    def list(self, collection: str) -> list[dict[str, Any]]:
        return [load_data(path) for path in sorted((self.root / collection).glob("*.json"))]

    def find_labels(self, *, case_id: str, image_id: str, organ: str) -> list[dict[str, Any]]:
        matches = []
        for record in self.list("labels"):
            if record["case_id"] != case_id or record["image_id"] != image_id:
                continue
            if record.get("artifact_lifecycle") != "active":
                continue
            for segment in record.get("segments", []):
                if segment["organ"] == organ:
                    matches.append(record)
                    break
        return matches

