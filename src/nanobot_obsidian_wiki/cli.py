"""Standalone CLI for the schema-driven Obsidian wiki sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from nanobot_obsidian_wiki.compile import WikiCompileWorkflow
from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.evaluation import format_eval_report, run_eval_suite
from nanobot_obsidian_wiki.intent_router import IntentRouter
from nanobot_obsidian_wiki.layered import LayeredKnowledgeEngine
from nanobot_obsidian_wiki.models import IntentResult
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine, format_search_results
from nanobot_obsidian_wiki.renderers.report import print_vault_status
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.ingest import IngestWorkflow
from nanobot_obsidian_wiki.workflows.lint import LintWorkflow
from nanobot_obsidian_wiki.workflows.query import QueryWorkflow

app = typer.Typer(
    name="nanobot-obsidian-wiki",
    help="Schema-driven Obsidian LLM Wiki sidecar CLI.",
    no_args_is_help=True,
)
console = Console()


def _get_guard(ctx: typer.Context) -> VaultGuard:
    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    return VaultGuard(vault)


def _load_schema(guard: VaultGuard):
    return SchemaLoader(guard.config).load()


def _runtime(vault: Path | str, *, dry_run: bool = True):
    config = WikiAgentConfig.from_vault(vault, dry_run=dry_run)
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)
    return config, guard, schema, obsidian


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


@app.callback()
def main(
    ctx: typer.Context,
    vault: Annotated[
        Path | None,
        typer.Option("--vault", "-v", help="Path to the Obsidian wiki vault."),
    ] = None,
) -> None:
    ctx.obj = {"vault": vault}


@app.command()
def check(ctx: typer.Context) -> None:
    """Validate that the vault has TheSchema.md, raw/, and wiki/."""

    guard = _get_guard(ctx)
    status = guard.check()
    print_vault_status(console, status)
    if not status.ok:
        console.print(f"[red]Missing:[/red] {', '.join(status.missing)}")
        raise typer.Exit(1)
    console.print("[green]Vault check passed.[/green]")


@app.command()
def ingest(
    ctx: typer.Context,
    source: Annotated[str, typer.Argument(help="Path to a raw/ source file.")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--execute")] = True,
) -> None:
    """Ingest a raw Markdown/Text file into source, concept, and entity pages."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    config = WikiAgentConfig.from_vault(vault, dry_run=dry_run)
    guard = VaultGuard(config)
    schema = _load_schema(guard)
    obsidian = ObsidianCLIAdapter(config, guard)
    workflow = IngestWorkflow(config, schema, guard, obsidian)
    try:
        report = workflow.execute(source, execute=not dry_run)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(report, markup=False)


@app.command()
def query(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Question to answer from wiki pages.")],
) -> None:
    """Summarize relevant wiki pages for a question."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    config = WikiAgentConfig.from_vault(vault)
    guard = VaultGuard(config)
    schema = _load_schema(guard)
    obsidian = ObsidianCLIAdapter(config, guard)
    workflow = QueryWorkflow(config, schema, guard, obsidian)
    console.print(workflow.answer(question), markup=False)


def _rag_engine(vault: Path | str) -> LocalRagEngine:
    config, guard, _schema, obsidian = _runtime(vault)
    return LocalRagEngine(config, guard, obsidian)


@app.command("rag-index")
def rag_index(
    ctx: typer.Context,
    scope: Annotated[
        str,
        typer.Option("--scope", help="RAG scope: wiki, raw, or all."),
    ] = "wiki",
    persist: Annotated[
        bool,
        typer.Option("--persist/--dry-run", help="Persist the index under wiki/.nanobot/."),
    ] = True,
) -> None:
    """Build a local chunk index for RAG retrieval."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        engine = _rag_engine(vault)
        index = engine.build_index([scope], persist=persist)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    mode = "persisted" if persist else "dry-run"
    console.print(
        (
            "# RAG Index\n\n"
            f"- mode: {mode}\n"
            f"- scopes: {', '.join(index.scopes)}\n"
            f"- files: {len(index.files)}\n"
            f"- chunks: {len(index.chunks)}\n"
            f"- index_path: {engine.index_path.relative_to(engine.config.vault_path).as_posix()}\n"
        ),
        markup=False,
    )


@app.command("rag-sync")
def rag_sync(
    ctx: typer.Context,
    scope: Annotated[
        str,
        typer.Option("--scope", help="RAG scope: wiki, raw, or all."),
    ] = "all",
    force: Annotated[
        bool,
        typer.Option("--force", help="Rebuild the Chroma collection instead of incremental sync."),
    ] = False,
) -> None:
    """Incrementally synchronize the persistent Chroma RAG index."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        engine = _rag_engine(vault)
        result = engine.sync_index([scope], force=force)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(
        (
            "# RAG Sync\n\n"
            f"- status: {result.status}\n"
            f"- scopes: {', '.join(result.scopes)}\n"
            f"- added_files: {len(result.added_files)}\n"
            f"- updated_files: {len(result.updated_files)}\n"
            f"- removed_files: {len(result.removed_files)}\n"
            f"- chunks: {result.chunks}\n"
            f"- index_path: {result.index_path}\n"
        ),
        markup=False,
    )


@app.command("rag-search")
def rag_search(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Question to retrieve evidence for.")],
    scope: Annotated[
        str,
        typer.Option("--scope", help="RAG scope: wiki, raw, or all."),
    ] = "wiki",
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=20)] = 5,
    use_cache: Annotated[bool, typer.Option("--cache/--fresh")] = False,
) -> None:
    """Retrieve chunk-level evidence from raw/wiki Markdown."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        engine = _rag_engine(vault)
        results = engine.search(question, top_k=top_k, scopes=[scope], use_cache=use_cache)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(format_search_results(results), markup=False)


@app.command("rag-answer")
def rag_answer(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Question to answer from retrieved evidence.")],
    scope: Annotated[
        str,
        typer.Option("--scope", help="RAG scope: wiki, raw, or all."),
    ] = "wiki",
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=20)] = 5,
    use_cache: Annotated[bool, typer.Option("--cache/--fresh")] = False,
) -> None:
    """Answer with chunk citations from the local RAG retriever."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        engine = _rag_engine(vault)
        answer = engine.answer(question, top_k=top_k, scopes=[scope], use_cache=use_cache)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(answer, markup=False)


@app.command("layered-answer")
def layered_answer(
    ctx: typer.Context,
    question: Annotated[str, typer.Argument(help="Question to route across Wiki and raw RAG.")],
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=20)] = 5,
    use_cache: Annotated[bool, typer.Option("--cache/--no-cache")] = True,
    auto_sync: Annotated[bool, typer.Option("--auto-sync/--no-sync")] = True,
) -> None:
    """Answer with Wiki/RAG routing, fusion, citations, and answer cache."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        config, guard, _schema, obsidian = _runtime(vault)
        result = LayeredKnowledgeEngine(config, guard, obsidian).answer(
            question,
            top_k=top_k,
            use_cache=use_cache,
            auto_sync=auto_sync,
        )
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(result.output, markup=False)


@app.command("rag-health")
def rag_health(
    ctx: typer.Context,
    scope: Annotated[
        str,
        typer.Option("--scope", help="RAG scope: wiki, raw, or all."),
    ] = "wiki",
) -> None:
    """Report RAG index coverage and cache freshness."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        engine = _rag_engine(vault)
        report = engine.health([scope])
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(report, markup=False)


@app.command("wiki-compile")
def wiki_compile(
    ctx: typer.Context,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Compile stable raw documents into wiki pages."),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 20,
    include_existing: Annotated[
        bool,
        typer.Option("--include-existing", help="Include raw documents that already have source pages."),
    ] = False,
) -> None:
    """Batch compile stable raw documents into the curated LLM Wiki."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        config, guard, schema, obsidian = _runtime(vault, dry_run=not execute)
        report = WikiCompileWorkflow(config, schema, guard, obsidian).run(
            execute=execute,
            limit=limit,
            include_existing=include_existing,
        )
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(report, markup=False)


@app.command("eval")
def eval_suite(
    ctx: typer.Context,
    cases: Annotated[
        Path | None,
        typer.Option("--cases", help="YAML eval case file. Defaults to built-in smoke cases."),
    ] = None,
) -> None:
    """Run Agent, wiki workflow, and RAG evaluation cases."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    try:
        result = run_eval_suite(vault, cases)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc
    console.print(format_eval_report(result), markup=False)
    if result.failed:
        raise typer.Exit(1)


@app.command()
def lint(
    ctx: typer.Context,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Apply low-risk frontmatter/summary fixes."),
    ] = False,
) -> None:
    """Check wiki health and optionally apply low-risk fixes."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)
    config = WikiAgentConfig.from_vault(vault, dry_run=not execute)
    guard = VaultGuard(config)
    schema = _load_schema(guard)
    obsidian = ObsidianCLIAdapter(config, guard)
    workflow = LintWorkflow(config, schema, guard, obsidian)
    console.print(workflow.generate_report(execute=execute), markup=False)


@app.command("run")
def run_intent(
    ctx: typer.Context,
    request: Annotated[str, typer.Argument(help="Natural-language wiki request.")],
    dry_run: Annotated[bool, typer.Option("--dry-run/--execute")] = True,
) -> None:
    """Route a natural-language request to ingest, query, or lint."""

    vault = (ctx.obj or {}).get("vault")
    if vault is None:
        console.print("[red]Error:[/red] --vault is required for this command.")
        raise typer.Exit(2)

    intent = IntentRouter().route(request)
    try:
        if intent.intent == "ingest":
            if not intent.raw_path:
                result = "Ingest 请求需要提供 raw/ 下的文件路径，例如 raw/sample.md。"
            else:
                config, guard, schema, obsidian = _runtime(vault, dry_run=dry_run)
                workflow = IngestWorkflow(config, schema, guard, obsidian)
                result = workflow.execute(intent.raw_path, execute=not dry_run)
        elif intent.intent == "lint":
            config, guard, schema, obsidian = _runtime(vault, dry_run=dry_run)
            workflow = LintWorkflow(config, schema, guard, obsidian)
            result = workflow.generate_report(execute=not dry_run)
        elif intent.intent == "query":
            config, guard, schema, obsidian = _runtime(vault)
            workflow = QueryWorkflow(config, schema, guard, obsidian)
            result = workflow.answer(intent.question or request)
        else:
            result = _unknown_result()
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        console.print(_format_run_result(intent, f"Error: {exc}"), markup=False)
        raise typer.Exit(1) from exc

    console.print(_format_run_result(intent, result), markup=False)


def run(argv: list[str] | None = None, **extra: Any) -> None:
    app(args=argv, **extra)
