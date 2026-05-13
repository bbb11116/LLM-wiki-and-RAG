from pathlib import Path
from shutil import copytree

from typer.testing import CliRunner

from nanobot_obsidian_wiki.cli import app

runner = CliRunner()


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    return vault


def test_run_ingest_routes_to_dry_run(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "run", "请基于 raw/sample.md 进行 Ingest"])

    assert result.exit_code == 0
    assert "## Intent" in result.stdout
    assert "- intent: ingest" in result.stdout
    assert "Ingest dry-run plan" in result.stdout
    assert not (vault / "wiki" / "sources" / "sample.md").exists()


def test_run_lint_routes_to_lint_workflow(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "run", "请对 wiki 做一次 Lint"])

    assert result.exit_code == 0
    assert "- intent: lint" in result.stdout
    assert "# Wiki Lint Report" in result.stdout


def test_run_query_routes_to_query_workflow(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "run", "AI Agent evaluation 讲了什么"])

    assert result.exit_code == 0
    assert "- intent: query" in result.stdout
    assert "## 候选依据页面" in result.stdout


def test_run_unknown_returns_guidance(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "run", "帮我处理一下"])

    assert result.exit_code == 0
    assert "- intent: unknown" in result.stdout
    assert "是要 Ingest" in result.stdout
    assert "是要 Query" in result.stdout
    assert "是要 Lint" in result.stdout


def test_run_default_does_not_write_files(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "run", "请基于 raw/sample.md 进行 Ingest"])

    assert result.exit_code == 0
    assert not (vault / "wiki" / "sources" / "sample.md").exists()


def test_run_execute_ingest_writes_source_page(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(
        app,
        ["--vault", str(vault), "run", "--execute", "请基于 raw/sample.md 进行 Ingest"],
    )

    assert result.exit_code == 0
    assert "Ingest executed" in result.stdout
    assert (vault / "wiki" / "sources" / "sample.md").exists()
