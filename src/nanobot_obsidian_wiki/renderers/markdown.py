"""Markdown rendering helpers."""

from __future__ import annotations

from nanobot_obsidian_wiki.models import WorkflowResult


def render_result_markdown(result: WorkflowResult) -> str:
    lines = [
        f"## {result.workflow.value}",
        "",
        result.message,
        "",
        f"- dry_run: {str(result.dry_run).lower()}",
    ]
    for key, value in result.details.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)

