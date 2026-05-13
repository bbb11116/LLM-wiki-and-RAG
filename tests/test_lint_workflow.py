from pathlib import Path
from shutil import copytree

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.schema_loader import SchemaLoader
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.lint import LintWorkflow


def _workflow(tmp_path: Path) -> LintWorkflow:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    _add_lint_pages(vault)
    config = WikiAgentConfig.from_vault(
        vault,
        obsidian_cmd="obsidian-cli-not-installed-for-test",
    )
    guard = VaultGuard(config)
    schema = SchemaLoader(config).load()
    obsidian = ObsidianCLIAdapter(config, guard)
    return LintWorkflow(config, schema, guard, obsidian)


def _add_lint_pages(vault: Path) -> None:
    concepts = vault / "wiki" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / "missing-frontmatter.md").write_text(
        "# Missing Frontmatter\n\nNo metadata and no links.\n",
        encoding="utf-8",
    )
    (concepts / "missing-summary.md").write_text(
        "---\n"
        "type: concept\n"
        "tags: []\n"
        "sources: []\n"
        "updated: 2026-05-08\n"
        "---\n\n"
        "# Missing Summary\n\nSee [[index]].\n",
        encoding="utf-8",
    )
    (concepts / "unresolved-link.md").write_text(
        "---\n"
        "type: concept\n"
        "tags: []\n"
        "summary: Has unresolved link\n"
        "sources: []\n"
        "updated: 2026-05-08\n"
        "---\n\n"
        "# Unresolved Link\n\nSee [[Does Not Exist]].\n",
        encoding="utf-8",
    )


def test_lint_scans_wiki_pages(tmp_path):
    workflow = _workflow(tmp_path)

    files = workflow.scan_wiki_files()

    assert "wiki/index.md" in files
    assert "wiki/concepts/missing-frontmatter.md" in files


def test_lint_finds_missing_frontmatter(tmp_path):
    workflow = _workflow(tmp_path)

    issues = workflow.check_frontmatter(workflow.scan_wiki_files())

    assert any(issue.code == "missing_frontmatter" for issue in issues)


def test_lint_finds_missing_summary(tmp_path):
    workflow = _workflow(tmp_path)

    issues = workflow.check_frontmatter(workflow.scan_wiki_files())

    assert any(issue.code == "missing_summary" and issue.path.endswith("missing-summary.md") for issue in issues)


def test_lint_finds_unresolved_link(tmp_path):
    workflow = _workflow(tmp_path)

    issues = workflow.check_unresolved_links(workflow.scan_wiki_files())

    assert any(issue.code == "unresolved_link" and issue.target == "Does Not Exist" for issue in issues)


def test_lint_resolves_title_link_to_slug_page(tmp_path):
    workflow = _workflow(tmp_path)
    entity = workflow.config.wiki_dir / "entities" / "ai-agent.md"
    entity.parent.mkdir(parents=True, exist_ok=True)
    entity.write_text(
        "---\n"
        "type: entity\n"
        "tags: []\n"
        "summary: AI Agent entity\n"
        "sources: []\n"
        "updated: 2026-05-08\n"
        "---\n\n"
        "# AI Agent\n\nSee [[index]].\n",
        encoding="utf-8",
    )

    issues = workflow.check_unresolved_links(workflow.scan_wiki_files())

    assert not any(issue.code == "unresolved_link" and issue.target == "AI Agent" for issue in issues)


def test_lint_finds_deadend_page(tmp_path):
    workflow = _workflow(tmp_path)

    issues = workflow.check_deadend_pages(workflow.scan_wiki_files())

    assert any(issue.code == "deadend_page" and issue.path.endswith("missing-frontmatter.md") for issue in issues)


def test_lint_default_report_does_not_modify_files(tmp_path):
    workflow = _workflow(tmp_path)
    before = _wiki_snapshot(workflow.config.wiki_dir)

    report = workflow.generate_report(execute=False)

    after = _wiki_snapshot(workflow.config.wiki_dir)
    assert "# Wiki Lint Report" in report
    assert after == before


def test_lint_execute_applies_only_low_risk_frontmatter_fixes(tmp_path):
    workflow = _workflow(tmp_path)

    workflow.generate_report(execute=True)

    fixed = (workflow.config.wiki_dir / "concepts" / "missing-frontmatter.md").read_text(
        encoding="utf-8"
    )
    missing_summary = (workflow.config.wiki_dir / "concepts" / "missing-summary.md").read_text(
        encoding="utf-8"
    )
    unresolved = (workflow.config.wiki_dir / "concepts" / "unresolved-link.md").read_text(
        encoding="utf-8"
    )
    assert fixed.startswith("---\n")
    assert "summary: 'TODO: add summary'" in fixed or "summary: TODO: add summary" in fixed
    assert "summary: 'TODO: add summary'" in missing_summary or "summary: TODO: add summary" in missing_summary
    assert "[[Does Not Exist]]" in unresolved


def test_lint_execute_appends_log(tmp_path):
    workflow = _workflow(tmp_path)

    workflow.generate_report(execute=True)

    log = (workflow.config.wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "Lint low-risk fixes applied" in log


def test_lint_execute_does_not_modify_raw(tmp_path):
    workflow = _workflow(tmp_path)
    raw_path = workflow.config.raw_dir / "sample.md"
    before = raw_path.read_text(encoding="utf-8")

    workflow.generate_report(execute=True)

    assert raw_path.read_text(encoding="utf-8") == before


def _wiki_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
        for path in root.rglob("*.md")
    }
