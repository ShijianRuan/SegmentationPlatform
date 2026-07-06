from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from segplatform.common import load_data
from segplatform.errors import ValidationError


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def schema_root() -> Path:
    return repository_root() / "registry" / "schemas"


def validate_schema(instance: Any, schema_name: str) -> None:
    root = schema_root()
    resources: list[tuple[str, Resource[Any]]] = []
    schemas: dict[str, Any] = {}
    for path in root.glob("*.schema.json"):
        schema = load_data(path)
        schemas[path.name] = schema
        if "$id" in schema:
            resources.append((schema["$id"], Resource.from_contents(schema)))

    if schema_name not in schemas:
        raise ValidationError(f"schema not found: {schema_name}")

    registry = Registry().with_resources(resources)
    validator = Draft202012Validator(schemas[schema_name], registry=registry)
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.absolute_path))
    if errors:
        messages = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            messages.append(f"{location}: {error.message}")
        raise ValidationError(f"{schema_name} validation failed:\n- " + "\n- ".join(messages))

