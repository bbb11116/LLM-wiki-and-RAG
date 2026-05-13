"""Public Python API for running Obsidian Wiki sidecar requests."""

from __future__ import annotations

import os
from pathlib import Path

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.intent_router import IntentRouter
from nanobot_obsidian_wiki.models import IntentResult
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.ingest import IngestWorkflow
from nanobot_obsidian_wiki.workflows.lint import LintWorkflow
from nanobot_obsidian_wiki.workflows.query import QueryWorkflow

ENV_VAULT_PATH = "NANOBOT_OBSIDIAN_VAULT_PATH"


def run_obsidian_wiki_request(
    vault_path: str | Path | None,
    request: str,
    execute: bool = False,
) -> str:
    """Run one natural-language Obsidian Wiki request through the safe sidecar stack."""

    resolved_vault = _resolve_vault_path(vault_path)
    intent = IntentRouter().route(request)

    if intent.intent == "unknown":
        return _format_run_result(intent, _unknown_result())

    config = WikiAgentConfig.from_vault(resolved_vault, dry_run=not execute)
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)

    if intent.intent == "ingest":
        if not intent.raw_path:
            result = "Ingest 请求需要提供 raw/ 下的文件路径，例如 raw/sample.md。"
        else:
            workflow = IngestWorkflow(config, schema, guard, obsidian)
            result = workflow.execute(intent.raw_path, execute=execute)
    elif intent.intent == "lint":
        workflow = LintWorkflow(config, schema, guard, obsidian)
        result = workflow.generate_report(execute=execute)
    elif intent.intent == "query":
        workflow = QueryWorkflow(config, schema, guard, obsidian)
        result = workflow.answer(intent.question or request)
    else:
        result = _unknown_result()

    return _format_run_result(intent, result)


def _resolve_vault_path(vault_path: str | Path | None) -> Path:
    value = vault_path or os.environ.get(ENV_VAULT_PATH)
    if not value:
        raise ValueError(
            "Obsidian vault path is required. Pass vault_path or set "
            f"{ENV_VAULT_PATH}."
        )
    return Path(value)


def _format_intent(intent: IntentResult) -> str:
    lines = [
        "## Intent",
        "",
        f"- intent: {intent.intent}",
        f"- confidence: {intent.confidence}",
        f"- reason: {intent.reason}",
    ]
    if intent.raw_path:
        lines.append(f"- raw_path: {intent.raw_path}")
    if intent.question:
        lines.append(f"- question: {intent.question}")
    return "\n".join(lines)


def _format_run_result(intent: IntentResult, result: str) -> str:
    return f"{_format_intent(intent)}\n\n## Result\n\n{result}"


def _unknown_result() -> str:
    return (
        "无法判断你的请求类型，请补充说明：\n\n"
        "- 是要 Ingest？请提供 raw/ 下的 .md 或 .txt 文件路径。\n"
        "- 是要 Query？请直接提出要基于 wiki 回答的问题。\n"
        "- 是要 Lint？请说明要检查知识库健康度。"
    )
