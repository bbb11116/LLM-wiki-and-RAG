"""Load TheSchema.md before running wiki workflows."""

from __future__ import annotations

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import WikiSchema


class SchemaLoader:
    """Load the vault schema file without attempting natural-language parsing."""

    def __init__(self, config: WikiAgentConfig):
        self._config = config

    def load(self) -> WikiSchema:
        schema_path = self._config.schema_path
        try:
            schema_text = schema_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise OSError(f"Could not read TheSchema.md at {schema_path}: {exc}") from exc
        if not schema_text.strip():
            raise ValueError(f"TheSchema.md is empty: {schema_path}")
        return WikiSchema(schema_text=schema_text)
