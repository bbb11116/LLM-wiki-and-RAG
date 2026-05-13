from pathlib import Path
from shutil import copytree

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.query import QueryWorkflow


def _workflow(tmp_path: Path) -> QueryWorkflow:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    config = WikiAgentConfig.from_vault(
        vault,
        obsidian_cmd="obsidian-cli-not-installed-for-test",
    )
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)
    return QueryWorkflow(config, schema, guard, obsidian)


def _wiki_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*.md")
    }


def test_query_reads_wiki_index(tmp_path):
    workflow = _workflow(tmp_path)

    context = workflow.build_context(["wiki/index.md"])

    assert "[PAGE] wiki/index.md" in context
    assert "Wiki Index" in context


def test_query_finds_wiki_page_containing_agent(tmp_path):
    workflow = _workflow(tmp_path)

    candidates = workflow.find_candidate_pages("AI Agent evaluation 讲了什么")

    assert "wiki/index.md" in candidates


def test_query_without_candidates_reports_insufficient_evidence(tmp_path):
    workflow = _workflow(tmp_path)

    answer = workflow.answer("zzzz-no-match")

    assert "未找到足够依据" in answer


def test_query_does_not_modify_files(tmp_path):
    workflow = _workflow(tmp_path)
    before = _wiki_snapshot(workflow.config.wiki_dir)

    workflow.answer("AI Agent evaluation 讲了什么")

    after = _wiki_snapshot(workflow.config.wiki_dir)
    assert after == before


def test_query_output_contains_candidate_section(tmp_path):
    workflow = _workflow(tmp_path)

    answer = workflow.answer("AI Agent evaluation 讲了什么")

    assert "## 候选依据页面" in answer
    assert "[[index]]" in answer
