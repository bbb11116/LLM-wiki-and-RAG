"""Console report rendering."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from nanobot_obsidian_wiki.models import VaultStatus, WorkflowResult


def print_vault_status(console: Console, status: VaultStatus) -> None:
    table = Table(title="Obsidian Wiki Vault Check")
    table.add_column("Item")
    table.add_column("Path")
    table.add_column("Status")
    table.add_row("vault", str(status.vault), "ok" if status.vault.is_dir() else "missing")
    table.add_row(
        "TheSchema.md",
        str(status.schema_path),
        "ok" if status.schema_path.is_file() else "missing",
    )
    table.add_row("raw/", str(status.raw_dir), "ok" if status.raw_dir.is_dir() else "missing")
    table.add_row("wiki/", str(status.wiki_dir), "ok" if status.wiki_dir.is_dir() else "missing")
    console.print(table)


def print_workflow_result(console: Console, result: WorkflowResult) -> None:
    console.print(f"[bold green]{result.workflow.value}[/bold green]: {result.message}")
    console.print(f"dry-run: {str(result.dry_run).lower()}")
    for key, value in result.details.items():
        console.print(f"{key}: {value}")

