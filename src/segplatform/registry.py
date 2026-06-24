from __future__ import annotations

from pathlib import Path
from typing import Any

from filelock import FileLock

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

# Fields that must not change when an existing record is updated via
# ``put(..., allow_update=True)``. Allowing the identity or ownership of a
# record to change on update would silently corrupt cross-collection references.
IMMUTABLE_FIELDS_BY_COLLECTION = {
    "cases": ("case_id",),
    "images": ("image_id", "case_id"),
    "labels": ("label_id", "case_id", "image_id"),
    "reviews": ("review_id",),
    "snapshots": ("snapshot_id",),
}


class FileRegistry:
    """Append-only file registry for the offline phase."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for collection in SCHEMA_BY_COLLECTION:
            (self.root / collection).mkdir(exist_ok=True)
        (self.root / "_indexes").mkdir(exist_ok=True)

    def _label_index_path(self) -> Path:
        return self.root / "_indexes" / "labels_by_case_image_organ.json"

    def _label_index_lock(self) -> FileLock:
        return FileLock(str(self._label_index_path()) + ".lock")

    def _load_label_index(self) -> dict[str, Any]:
        path = self._label_index_path()
        if not path.exists():
            return {}
        return load_data(path)

    def _label_index_key(self, case_id: str, image_id: str, organ: str) -> str:
        return "\t".join((case_id, image_id, organ))

    def rebuild_label_index(self) -> dict[str, Any]:
        with self._label_index_lock():
            index: dict[str, list[str]] = {}
            for record in self.list("labels"):
                if record.get("artifact_lifecycle") != "active":
                    continue
                for segment in record.get("segments", []):
                    key = self._label_index_key(record["case_id"], record["image_id"], segment["organ"])
                    index.setdefault(key, []).append(record["label_id"])
            for key in list(index):
                index[key] = sorted(set(index[key]))
            payload = {"schema_version": "label_index.v1", "updated_at": utc_now(), "items": index}
            write_json(self._label_index_path(), payload)
            return payload

    def _update_label_index(self, record: dict[str, Any], previous: dict[str, Any] | None = None) -> None:
        with self._label_index_lock():
            payload = self._load_label_index()
            if payload.get("schema_version") != "label_index.v1":
                payload = {"schema_version": "label_index.v1", "items": {}}
            items = payload.setdefault("items", {})
            label_id = record["label_id"]
            for values in items.values():
                while label_id in values:
                    values.remove(label_id)
            if previous:
                previous_id = previous["label_id"]
                for values in items.values():
                    while previous_id in values:
                        values.remove(previous_id)
            if record.get("artifact_lifecycle") == "active":
                for segment in record.get("segments", []):
                    key = self._label_index_key(record["case_id"], record["image_id"], segment["organ"])
                    values = items.setdefault(key, [])
                    if label_id not in values:
                        values.append(label_id)
                        values.sort()
            payload["updated_at"] = utc_now()
            write_json(self._label_index_path(), payload)

    def put(self, collection: str, record: dict[str, Any], *, allow_update: bool = False) -> Path:
        if collection not in SCHEMA_BY_COLLECTION:
            raise ValueError(f"unknown registry collection: {collection}")
        validate_schema(record, SCHEMA_BY_COLLECTION[collection])
        identifier = canonical_id(str(record[ID_FIELD_BY_COLLECTION[collection]]), ID_FIELD_BY_COLLECTION[collection])
        path = self.root / collection / f"{identifier}.json"
        if path.exists() and not allow_update:
            raise ValidationError(f"immutable registry record already exists: {path}")
        previous = load_data(path) if path.exists() else None
        if allow_update and previous:
            for field in IMMUTABLE_FIELDS_BY_COLLECTION.get(collection, ()):
                if record.get(field) != previous.get(field):
                    raise ValidationError(
                        f"immutable field '{field}' cannot change on update: {collection}/{identifier}"
                    )
            record.setdefault("updated_at", utc_now())
            record.setdefault("created_at", previous.get("created_at", utc_now()))
        write_json(path, record)
        if collection == "labels":
            self._update_label_index(record, previous)
        return path

    def get(self, collection: str, identifier: str) -> dict[str, Any]:
        path = self.root / collection / f"{canonical_id(identifier)}.json"
        if not path.exists():
            raise ValidationError(f"registry record not found: {collection}/{identifier}")
        return load_data(path)

    def list(self, collection: str) -> list[dict[str, Any]]:
        return [load_data(path) for path in sorted((self.root / collection).glob("*.json"))]

    def find_labels(self, *, case_id: str, image_id: str, organ: str) -> list[dict[str, Any]]:
        payload = self._load_label_index()
        if payload.get("schema_version") != "label_index.v1":
            payload = self.rebuild_label_index()
        label_ids = payload.get("items", {}).get(self._label_index_key(case_id, image_id, organ), [])
        matches = []
        for label_id in label_ids:
            record = self.get("labels", label_id)
            if record["case_id"] != case_id or record["image_id"] != image_id:
                continue
            if record.get("artifact_lifecycle") != "active":
                continue
            for segment in record.get("segments", []):
                if segment["organ"] == organ:
                    matches.append(record)
                    break
        return matches
