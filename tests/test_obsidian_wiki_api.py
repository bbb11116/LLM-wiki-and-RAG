from pathlib import Path
from shutil import copytree

from nanobot_obsidian_wiki.api import ENV_VAULT_PATH, run_obsidian_wiki_request


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    return vault


def test_run_obsidian_wiki_request_routes_query(tmp_path):
    vault = _vault(tmp_path)

    result = run_obsidian_wiki_request(vault, "AI Agent evaluation 讲了什么")

    assert "## Intent" in result
    assert "- intent: query" in result
    assert "## 候选依据页面" in result


def test_run_obsidian_wiki_request_uses_env_vault_path(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    monkeypatch.setenv(ENV_VAULT_PATH, str(vault))

    result = run_obsidian_wiki_request(None, "请对 wiki 做一次 Lint")

    assert "- intent: lint" in result
    assert "# Wiki Lint Report" in result


def test_run_obsidian_wiki_request_default_dry_run_does_not_write(tmp_path):
    vault = _vault(tmp_path)

    result = run_obsidian_wiki_request(vault, "请基于 raw/sample.md 进行 Ingest")

    assert "Ingest dry-run plan" in result
    assert not (vault / "wiki" / "sources" / "sample.md").exists()


def test_run_obsidian_wiki_request_execute_ingest_writes(tmp_path):
    vault = _vault(tmp_path)

    result = run_obsidian_wiki_request(vault, "请基于 raw/sample.md 进行 Ingest", execute=True)

    assert "Ingest executed" in result
    assert (vault / "wiki" / "sources" / "sample.md").exists()
