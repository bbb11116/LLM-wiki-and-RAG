from pathlib import Path
from shutil import copytree

from typer.testing import CliRunner

from nanobot_obsidian_wiki.cli import app
from nanobot_obsidian_wiki.evaluation import format_eval_report, run_eval_suite

runner = CliRunner()


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    return vault


def test_eval_runner_default_cases_pass(tmp_path):
    vault = _vault(tmp_path)

    result = run_eval_suite(vault)

    assert result.failed == 0
    assert result.passed == result.total
    assert "pass_rate: 100.0%" in format_eval_report(result)


def test_eval_runner_loads_yaml_cases(tmp_path):
    vault = _vault(tmp_path)
    cases = tmp_path / "cases.yaml"
    cases.write_text(
        """
cases:
  - id: query_contains_rag_section
    type: workflow
    input: "AI Agent evaluation 讲了什么"
    expected:
      must_contain:
        - "## RAG 证据片段"
""".strip(),
        encoding="utf-8",
    )

    result = run_eval_suite(vault, cases)

    assert result.failed == 0
    assert result.total == 1


def test_cli_eval_outputs_report(tmp_path):
    vault = _vault(tmp_path)

    result = runner.invoke(app, ["--vault", str(vault), "eval"])

    assert result.exit_code == 0
    assert "# Agent Evaluation Report" in result.stdout
    assert "pass_rate: 100.0%" in result.stdout
