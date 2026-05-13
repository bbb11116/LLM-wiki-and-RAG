"""Shared models for the Obsidian Wiki sidecar CLI."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class WorkflowName(str, Enum):
    """Supported first-stage workflow names."""

    check = "check"
    ingest = "ingest"
    query = "query"
    lint = "lint"


class WikiSchema(BaseModel):
    """Schema rules loaded from TheSchema.md with conservative defaults."""

    schema_text: str
    raw_dir_name: str = "raw"
    wiki_dir_name: str = "wiki"
    page_type_dirs: dict[str, str] = Field(
        default_factory=lambda: {
            "source": "wiki/sources",
            "entity": "wiki/entities",
            "concept": "wiki/concepts",
            "comparison": "wiki/comparisons",
            "overview": "wiki/overview",
        }
    )
    workflows: list[Literal["ingest", "query", "lint"]] = Field(
        default_factory=lambda: ["ingest", "query", "lint"]
    )
    read_only_dirs: list[str] = Field(default_factory=lambda: ["raw"])
    writable_dirs: list[str] = Field(default_factory=lambda: ["wiki"])


class IntentResult(BaseModel):
    """Classified user intent for future workflow routing."""

    intent: Literal["ingest", "query", "lint", "unknown"]
    confidence: float
    raw_path: str | None = None
    question: str | None = None
    reason: str


class CLIResult(BaseModel):
    """Captured result from an external CLI invocation."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class WritePlan(BaseModel):
    """Dry-run write plan shown before any wiki mutation."""

    title: str
    summary: str
    files_to_create: list[str] = Field(default_factory=list)
    files_to_update: list[str] = Field(default_factory=list)
    files_to_append: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_confirmation: bool = True


class VaultStatus(BaseModel):
    """Result of validating an Obsidian wiki vault layout."""

    vault: Path
    schema_path: Path
    raw_dir: Path
    wiki_dir: Path
    ok: bool
    missing: list[str] = Field(default_factory=list)


class WorkflowResult(BaseModel):
    """Small display-friendly workflow result."""

    workflow: WorkflowName
    message: str
    dry_run: bool = True
    details: dict[str, str] = Field(default_factory=dict)


class LintIssue(BaseModel):
    """Placeholder lint issue model for the upcoming real lint workflow."""

    code: str
    path: Path | None = None
    message: str
    severity: str = "warning"
