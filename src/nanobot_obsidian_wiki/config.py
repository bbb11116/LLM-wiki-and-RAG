"""Configuration model for Obsidian wiki workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WikiAgentConfig(BaseModel):
    """Resolved and validated configuration for an Obsidian wiki vault."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    vault_path: Path
    schema_path: Path | None = None
    raw_dir: Path | None = None
    wiki_dir: Path | None = None
    dry_run: bool = True
    require_confirmation_for_write: bool = True
    obsidian_cmd: str = "obsidian"
    max_file_size_mb: int = Field(default=20, gt=0)
    log_file: Path | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_paths(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {
                key: Path(value).expanduser() if key.endswith(("_path", "_dir", "_file")) and value is not None else value
                for key, value in data.items()
            }
        return data

    @model_validator(mode="after")
    def _resolve_and_validate(self) -> "WikiAgentConfig":
        vault_path = self.vault_path.expanduser().resolve()
        schema_path = (self.schema_path or vault_path / "TheSchema.md").expanduser().resolve()
        raw_dir = (self.raw_dir or vault_path / "raw").expanduser().resolve()
        wiki_dir = (self.wiki_dir or vault_path / "wiki").expanduser().resolve()
        log_file = (self.log_file or wiki_dir / "log.md").expanduser().resolve()

        if not vault_path.is_dir():
            raise ValueError(f"Vault path does not exist or is not a directory: {vault_path}")
        if not schema_path.is_file():
            raise ValueError(f"TheSchema.md was not found: {schema_path}")
        if not raw_dir.is_dir():
            raise ValueError(f"raw/ directory was not found: {raw_dir}")
        if not wiki_dir.is_dir():
            raise ValueError(f"wiki/ directory was not found: {wiki_dir}")

        self.vault_path = vault_path
        self.schema_path = schema_path
        self.raw_dir = raw_dir
        self.wiki_dir = wiki_dir
        self.log_file = log_file
        return self

    @classmethod
    def from_vault(cls, vault: str | Path, **overrides: Any) -> "WikiAgentConfig":
        return cls(vault_path=Path(vault), **overrides)

    @property
    def vault(self) -> Path:
        """Backward-compatible alias used by first-stage display code."""

        return self.vault_path

    @property
    def log_path(self) -> Path:
        """Backward-compatible alias for the append-only wiki log."""

        return self.log_file

