from pathlib import Path
from shutil import copytree

from typer.testing import CliRunner

from nanobot_obsidian_wiki.cli import app
from nanobot_obsidian_wiki.compile import WikiCompileWorkflow
from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.layered import LayeredKnowledgeEngine
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard

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


def test_rag_sync_updates_changed_raw_file(tmp_path):
    vault = _vault(tmp_path)
    config, guard, _schema, obsidian = _runtime(vault)
    engine = LocalRagEngine(config, guard, obsidian)

    first = engine.sync_index(["all"])
    (vault / "raw" / "sample.md").write_text(
        "# AI Agent Evaluation\n\nNew routing cache evidence.",
        encoding="utf-8",
    )
    second = engine.sync_index(["all"])

    assert first.status in {"created", "rebuilt"}
    assert second.status == "updated"
    assert "raw/sample.md" in second.updated_files


def test_layered_answer_uses_wiki_first_route_and_cache(tmp_path):
    vault = _vault(tmp_path)
    config, guard, _schema, obsidian = _runtime(vault)
    engine = LayeredKnowledgeEngine(config, guard, obsidian)

    first = engine.answer("AI Agent evaluation 是什么？")
    second = engine.answer("AI Agent evaluation 是什么？")

    assert "# Layered Knowledge Answer" in first.output
    assert "- route: wiki_first" in first.output
    assert "## Citations" in first.output
    assert "- cache: hit" in second.output


def test_layered_answer_routes_realtime_to_raw(tmp_path):
    vault = _vault(tmp_path)
    config, guard, _schema, obsidian = _runtime(vault)

    answer = LayeredKnowledgeEngine(config, guard, obsidian).answer(
        "今天最新 AI Agent evaluation 公告是什么？",
        use_cache=False,
    )

    assert "- route: raw_only" in answer.output


def test_wiki_compile_dry_run_does_not_write(tmp_path):
    vault = _vault(tmp_path)
    config, guard, schema, obsidian = _runtime(vault)
    config.dry_run = True

    report = WikiCompileWorkflow(config, schema, guard, obsidian).run(execute=False)

    assert "# Wiki Compile Plan" in report
    assert not (vault / "wiki" / "sources" / "sample.md").exists()


def test_wiki_compile_execute_writes_source(tmp_path):
    vault = _vault(tmp_path)
    config, guard, schema, obsidian = _runtime(vault)

    report = WikiCompileWorkflow(config, schema, guard, obsidian).run(execute=True)

    assert "# Wiki Compile Result" in report
    assert (vault / "wiki" / "sources" / "sample.md").exists()


def test_cli_layered_answer(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(
        app,
        ["--vault", str(vault), "layered-answer", "AI Agent evaluation 是什么？"],
    )

    assert result.exit_code == 0
    assert "# Layered Knowledge Answer" in result.stdout


def test_cli_rag_sync(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "rag-sync"])

    assert result.exit_code == 0
    assert "# RAG Sync" in result.stdout


def test_cli_wiki_compile_dry_run(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "wiki-compile"])

    assert result.exit_code == 0
    assert "# Wiki Compile Plan" in result.stdout
    assert not (vault / "wiki" / "sources" / "sample.md").exists()
