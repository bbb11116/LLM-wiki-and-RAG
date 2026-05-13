from pathlib import Path

from typer.testing import CliRunner

from nanobot_obsidian_wiki.cli import app

runner = CliRunner()


def test_cli_help_runs():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "ingest" in result.stdout
    assert "query" in result.stdout
    assert "lint" in result.stdout


def test_cli_check_detects_sample_vault():
    vault = Path("tests/fixtures/sample_vault")

    result = runner.invoke(app, ["--vault", str(vault), "check"])

    assert result.exit_code == 0
    assert "Vault check passed" in result.stdout
    assert "TheSchema.md" in result.stdout
    assert "raw/" in result.stdout
    assert "wiki/" in result.stdout

