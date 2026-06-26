from __future__ import annotations

from pathlib import Path

from segplatform.common import load_data
from segplatform.errors import ValidationError
from segplatform.schema import repository_root


class AnatomyVocabulary:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or repository_root() / "config" / "anatomy_vocabulary.yaml"
        data = load_data(self.path)
        self.organs: dict[str, dict] = data.get("organs", {})
        self.aliases: dict[str, str] = {}
        for organ, details in self.organs.items():
            self.aliases[organ.lower()] = organ
            for alias in details.get("aliases", []):
                self.aliases[str(alias).lower()] = organ

    def normalize(self, name: str) -> str:
        normalized = self.aliases.get(name.strip().lower())
        if not normalized:
            raise ValidationError(f"unknown organ name: {name}")
        return normalized

    def require_all(self, names: list[str]) -> list[str]:
        normalized = [self.normalize(name) for name in names]
        if len(normalized) != len(set(normalized)):
            raise ValidationError(f"duplicate organ after alias normalization: {names}")
        return normalized

