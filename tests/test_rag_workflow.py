from pathlib import Path
from shutil import copytree

from typer.testing import CliRunner

from nanobot_obsidian_wiki.cli import app
from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine, format_search_results
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.ingest import IngestWorkflow
from nanobot_obsidian_wiki.workflows.query import QueryWorkflow

runner = CliRunner()


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    return vault


def _runtime(vault: Path):
    config = WikiAgentConfig.from_vault(
        vault,
        dry_run=False,
        obsidian_cmd="obsidian-cli-not-installed-for-test",
    )
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)
    return config, guard, schema, obsidian


def _engine(vault: Path) -> LocalRagEngine:
    config, guard, _schema, obsidian = _runtime(vault)
    return LocalRagEngine(config, guard, obsidian)


def test_rag_search_retrieves_raw_sample_with_all_scope(tmp_path):
    vault = _vault(tmp_path)
    engine = _engine(vault)

    results = engine.search("agent evaluation tool safety", scopes=["all"], top_k=3)

    assert results
    assert any(result.chunk.path == "raw/sample.md" for result in results)
    assert "# RAG Search Results" in format_search_results(results)


def test_rag_answer_includes_chunk_citation(tmp_path):
    vault = _vault(tmp_path)
    engine = _engine(vault)

    answer = engine.answer("AI Agent evaluation measures what?", scopes=["all"])

    assert "## 引用" in answer
    assert "#chunk-" in answer
    assert "[raw/sample.md#chunk-" in answer or "[wiki/index.md#chunk-" in answer


def test_rag_index_persists_under_wiki_cache(tmp_path):
    vault = _vault(tmp_path)
    engine = _engine(vault)

    index = engine.build_index(["all"], persist=True)

    cache = vault / "wiki" / ".nanobot" / "chroma"
    assert cache.exists()
    assert cache.is_dir()
    assert len(index.chunks) > 0
    loaded = engine.load_index()
    assert loaded is not None
    assert "raw/sample.md" in loaded.files


def test_query_workflow_includes_rag_evidence_section(tmp_path):
    vault = _vault(tmp_path)
    config, guard, schema, obsidian = _runtime(vault)
    workflow = QueryWorkflow(config, schema, guard, obsidian)

    answer = workflow.answer("AI Agent evaluation 讲了什么")

    assert "## RAG 证据片段" in answer
    assert "# RAG Search Results" in answer


def test_rag_search_sees_ingested_source_pages(tmp_path):
    vault = _vault(tmp_path)
    config, guard, schema, obsidian = _runtime(vault)
    IngestWorkflow(config, schema, guard, obsidian).execute("raw/sample.md", execute=True)
    engine = LocalRagEngine(config, guard, obsidian)

    results = engine.search("schema rules source traceability", scopes=["wiki"], top_k=5)

    assert any(result.chunk.path == "wiki/sources/sample.md" for result in results)


def test_cli_rag_answer(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(
        app,
        [
            "--vault",
            str(vault),
            "rag-answer",
            "--scope",
            "all",
            "AI Agent evaluation measures what?",
        ],
    )

    assert result.exit_code == 0
    assert "## 引用" in result.stdout
