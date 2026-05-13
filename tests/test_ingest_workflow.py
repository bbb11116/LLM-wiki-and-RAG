from pathlib import Path
from shutil import copytree

import pytest

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.ingest import IngestWorkflow


def _workflow(tmp_path: Path, *, dry_run: bool = True) -> IngestWorkflow:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    config = WikiAgentConfig.from_vault(
        vault,
        dry_run=dry_run,
        obsidian_cmd="obsidian-cli-not-installed-for-test",
    )
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)
    return IngestWorkflow(config, schema, guard, obsidian)


def test_ingest_dry_run_does_not_create_source_page(tmp_path):
    workflow = _workflow(tmp_path, dry_run=True)

    report = workflow.execute("raw/sample.md", execute=False)

    assert "Ingest dry-run plan" in report
    assert not (workflow.config.wiki_dir / "sources" / "sample.md").exists()


def test_ingest_execute_creates_source_page(tmp_path):
    workflow = _workflow(tmp_path, dry_run=False)

    report = workflow.execute("raw/sample.md", execute=True)

    source = workflow.config.wiki_dir / "sources" / "sample.md"
    assert "Ingest executed" in report
    assert source.exists()
    assert "type: source" in source.read_text(encoding="utf-8")


def test_ingest_execute_creates_concept_and_entity_pages(tmp_path):
    workflow = _workflow(tmp_path, dry_run=False)

    report = workflow.execute("raw/sample.md", execute=True)

    concept = workflow.config.wiki_dir / "concepts" / "ai-agent-evaluation.md"
    entity = workflow.config.wiki_dir / "entities" / "ai-agent.md"
    assert "wiki/concepts/ai-agent-evaluation.md" in report
    assert "wiki/entities/ai-agent.md" in report
    assert concept.exists()
    assert entity.exists()
    assert "type: concept" in concept.read_text(encoding="utf-8")
    assert "type: entity" in entity.read_text(encoding="utf-8")
    assert "raw/sample.md" in concept.read_text(encoding="utf-8")
    assert "raw/sample.md" in entity.read_text(encoding="utf-8")


def test_ingest_execute_appends_log(tmp_path):
    workflow = _workflow(tmp_path, dry_run=False)

    workflow.execute("raw/sample.md", execute=True)

    log = (workflow.config.wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "Ingested raw/sample.md -> wiki/sources/sample.md" in log
    assert "wiki/concepts/ai-agent-evaluation.md" in log
    assert "wiki/entities/ai-agent.md" in log


def test_ingest_execute_updates_index(tmp_path):
    workflow = _workflow(tmp_path, dry_run=False)

    workflow.execute("raw/sample.md", execute=True)

    index = (workflow.config.wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "[[sources/sample]]" in index
    assert "[[concepts/ai-agent-evaluation]]" in index
    assert "[[entities/ai-agent]]" in index


def test_ingest_rejects_non_raw_path(tmp_path):
    workflow = _workflow(tmp_path, dry_run=True)

    with pytest.raises(PermissionError, match="raw/"):
        workflow.build_plan("wiki/index.md")


def test_ingest_pdf_returns_clear_error(tmp_path):
    workflow = _workflow(tmp_path, dry_run=True)
    pdf = workflow.config.raw_dir / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="不支持 PDF，请先转换为 Markdown"):
        workflow.build_plan("raw/sample.pdf")


def test_ingest_repeated_execute_does_not_duplicate_index_link(tmp_path):
    workflow = _workflow(tmp_path, dry_run=False)

    workflow.execute("raw/sample.md", execute=True)
    workflow.execute("raw/sample.md", execute=True)

    index = (workflow.config.wiki_dir / "index.md").read_text(encoding="utf-8")
    assert index.count("[[sources/sample]]") == 1
    assert index.count("[[concepts/ai-agent-evaluation]]") == 1
    assert index.count("[[entities/ai-agent]]") == 1
