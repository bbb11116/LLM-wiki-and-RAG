"""MCP stdio server for the Schema-driven Obsidian Wiki sidecar."""

from __future__ import annotations

from nanobot_obsidian_wiki.api import run_obsidian_wiki_request
from nanobot_obsidian_wiki.compile import WikiCompileWorkflow
from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.evaluation import format_eval_report, run_eval_suite
from nanobot_obsidian_wiki.layered import LayeredKnowledgeEngine
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine, format_search_results
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard

SERVER_NAME = "nanobot-obsidian-wiki"


def run_obsidian_wiki_tool(
    request: str,
    vault_path: str | None = None,
    execute: bool = False,
) -> str:
    """Run an Obsidian Wiki request through the sidecar API."""

    if not request or not request.strip():
        return "Error: request is required."
    return run_obsidian_wiki_request(vault_path, request, execute=execute)


def _rag_engine(vault_path: str | None) -> LocalRagEngine:
    from nanobot_obsidian_wiki.api import _resolve_vault_path

    config = WikiAgentConfig.from_vault(_resolve_vault_path(vault_path))
    guard = VaultGuard(config)
    obsidian = ObsidianCLIAdapter(config, guard)
    return LocalRagEngine(config, guard, obsidian)


def run_obsidian_rag_index_tool(
    vault_path: str | None = None,
    scope: str = "wiki",
    persist: bool = True,
) -> str:
    """Build a local RAG index for the configured vault."""

    engine = _rag_engine(vault_path)
    index = engine.build_index([scope], persist=persist)
    mode = "persisted" if persist else "dry-run"
    return (
        "# RAG Index\n\n"
        f"- mode: {mode}\n"
        f"- scopes: {', '.join(index.scopes)}\n"
        f"- files: {len(index.files)}\n"
        f"- chunks: {len(index.chunks)}\n"
        f"- index_path: {engine.index_path.relative_to(engine.config.vault_path).as_posix()}\n"
    )


def run_obsidian_rag_search_tool(
    question: str,
    vault_path: str | None = None,
    scope: str = "wiki",
    top_k: int = 5,
    use_cache: bool = False,
) -> str:
    """Search chunk-level evidence from the configured vault."""

    if not question or not question.strip():
        return "Error: question is required."
    engine = _rag_engine(vault_path)
    results = engine.search(question, top_k=top_k, scopes=[scope], use_cache=use_cache)
    return format_search_results(results)


def run_obsidian_rag_answer_tool(
    question: str,
    vault_path: str | None = None,
    scope: str = "wiki",
    top_k: int = 5,
    use_cache: bool = False,
) -> str:
    """Answer from retrieved evidence with chunk citations."""

    if not question or not question.strip():
        return "Error: question is required."
    engine = _rag_engine(vault_path)
    return engine.answer(question, top_k=top_k, scopes=[scope], use_cache=use_cache)


def run_obsidian_rag_sync_tool(
    vault_path: str | None = None,
    scope: str = "all",
    force: bool = False,
) -> str:
    """Incrementally sync the persistent Chroma RAG index."""

    engine = _rag_engine(vault_path)
    result = engine.sync_index([scope], force=force)
    return (
        "# RAG Sync\n\n"
        f"- status: {result.status}\n"
        f"- scopes: {', '.join(result.scopes)}\n"
        f"- added_files: {len(result.added_files)}\n"
        f"- updated_files: {len(result.updated_files)}\n"
        f"- removed_files: {len(result.removed_files)}\n"
        f"- chunks: {result.chunks}\n"
        f"- index_path: {result.index_path}\n"
    )


def run_obsidian_layered_answer_tool(
    question: str,
    vault_path: str | None = None,
    top_k: int = 5,
    use_cache: bool = True,
    auto_sync: bool = True,
) -> str:
    """Answer through Wiki/raw RAG routing, fusion, citations, and cache."""

    if not question or not question.strip():
        return "Error: question is required."
    from nanobot_obsidian_wiki.api import _resolve_vault_path

    config = WikiAgentConfig.from_vault(_resolve_vault_path(vault_path))
    guard = VaultGuard(config)
    obsidian = ObsidianCLIAdapter(config, guard)
    return LayeredKnowledgeEngine(config, guard, obsidian).answer(
        question,
        top_k=top_k,
        use_cache=use_cache,
        auto_sync=auto_sync,
    ).output


def run_obsidian_wiki_compile_tool(
    vault_path: str | None = None,
    execute: bool = False,
    limit: int = 20,
    include_existing: bool = False,
) -> str:
    """Compile stable raw documents into the curated LLM Wiki."""

    from nanobot_obsidian_wiki.api import _resolve_vault_path

    config = WikiAgentConfig.from_vault(_resolve_vault_path(vault_path), dry_run=not execute)
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)
    return WikiCompileWorkflow(config, schema, guard, obsidian).run(
        execute=execute,
        limit=limit,
        include_existing=include_existing,
    )


def run_obsidian_eval_tool(
    vault_path: str | None = None,
    cases_path: str | None = None,
) -> str:
    """Run structured workflow/RAG/layered-answer evaluation cases."""

    from nanobot_obsidian_wiki.api import _resolve_vault_path

    result = run_eval_suite(_resolve_vault_path(vault_path), cases_path)
    return format_eval_report(result)


def create_server():
    """Create the FastMCP server lazily so importing this module stays lightweight."""

    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(SERVER_NAME)

    @mcp.tool()
    def obsidian_wiki(
        request: str,
        vault_path: str | None = None,
        execute: bool = False,
    ) -> str:
        """Run Obsidian Wiki Ingest, Query, or Lint safely.

        Args:
            request: Natural-language Obsidian Wiki request, such as ingesting
                raw/sample.md, checking wiki health, or answering from wiki pages.
            vault_path: Path to the Obsidian vault. If omitted,
                NANOBOT_OBSIDIAN_VAULT_PATH is used.
            execute: When true, allow write-capable workflows to perform
                low-risk writes. Defaults to false/dry-run.
        """

        return run_obsidian_wiki_tool(
            vault_path=vault_path,
            request=request,
            execute=execute,
        )

    @mcp.tool()
    def obsidian_rag_index(
        vault_path: str | None = None,
        scope: str = "wiki",
        persist: bool = True,
    ) -> str:
        """Build a local RAG index over wiki, raw, or all allowed vault files."""

        return run_obsidian_rag_index_tool(
            vault_path=vault_path,
            scope=scope,
            persist=persist,
        )

    @mcp.tool()
    def obsidian_rag_search(
        question: str,
        vault_path: str | None = None,
        scope: str = "wiki",
        top_k: int = 5,
        use_cache: bool = False,
    ) -> str:
        """Retrieve chunk-level evidence from the local Obsidian vault."""

        return run_obsidian_rag_search_tool(
            question=question,
            vault_path=vault_path,
            scope=scope,
            top_k=top_k,
            use_cache=use_cache,
        )

    @mcp.tool()
    def obsidian_rag_answer(
        question: str,
        vault_path: str | None = None,
        scope: str = "wiki",
        top_k: int = 5,
        use_cache: bool = False,
    ) -> str:
        """Answer with citations from retrieved RAG evidence chunks."""

        return run_obsidian_rag_answer_tool(
            question=question,
            vault_path=vault_path,
            scope=scope,
            top_k=top_k,
            use_cache=use_cache,
        )

    @mcp.tool()
    def obsidian_rag_sync(
        vault_path: str | None = None,
        scope: str = "all",
        force: bool = False,
    ) -> str:
        """Incrementally sync the persistent Chroma RAG index."""

        return run_obsidian_rag_sync_tool(
            vault_path=vault_path,
            scope=scope,
            force=force,
        )

    @mcp.tool()
    def obsidian_layered_answer(
        question: str,
        vault_path: str | None = None,
        top_k: int = 5,
        use_cache: bool = True,
        auto_sync: bool = True,
    ) -> str:
        """Answer using Wiki-first/raw-fallback routing and evidence fusion."""

        return run_obsidian_layered_answer_tool(
            question=question,
            vault_path=vault_path,
            top_k=top_k,
            use_cache=use_cache,
            auto_sync=auto_sync,
        )

    @mcp.tool()
    def obsidian_wiki_compile(
        vault_path: str | None = None,
        execute: bool = False,
        limit: int = 20,
        include_existing: bool = False,
    ) -> str:
        """Compile stable raw documents into the curated LLM Wiki."""

        return run_obsidian_wiki_compile_tool(
            vault_path=vault_path,
            execute=execute,
            limit=limit,
            include_existing=include_existing,
        )

    @mcp.tool()
    def obsidian_eval(
        vault_path: str | None = None,
        cases_path: str | None = None,
    ) -> str:
        """Run Obsidian Wiki Agent eval cases and return a Markdown report."""

        return run_obsidian_eval_tool(
            vault_path=vault_path,
            cases_path=cases_path,
        )

    return mcp


def main() -> None:
    """Run the MCP server over stdio."""

    create_server().run()


if __name__ == "__main__":
    main()
