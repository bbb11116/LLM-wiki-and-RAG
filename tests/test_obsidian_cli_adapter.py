from pathlib import Path
from shutil import copytree

import pytest

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.vault_guard import VaultGuard


def _adapter(tmp_path: Path) -> ObsidianCLIAdapter:
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)
    config = WikiAgentConfig.from_vault(vault, obsidian_cmd="obsidian-cli-not-installed-for-test")
    guard = VaultGuard(config)
    return ObsidianCLIAdapter(config, guard)


def test_read_note_falls_back_when_cli_unavailable(tmp_path):
    adapter = _adapter(tmp_path)

    content = adapter.read_note("wiki/index.md")

    assert "Wiki Index" in content
    assert adapter.check_available() is False
    assert adapter.last_warning
    assert "fallback" in adapter.last_warning


def test_create_or_update_note_writes_wiki_file_with_fallback(tmp_path):
    adapter = _adapter(tmp_path)

    adapter.create_or_update_note("wiki/sources/demo.md", "# Demo\n")

    assert (adapter.config.wiki_dir / "sources" / "demo.md").read_text(encoding="utf-8") == "# Demo\n"


def test_writes_use_guarded_filesystem_even_when_cli_available(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path)
    adapter._available = True

    def fail_run(*_args, **_kwargs):
        raise AssertionError("write operations must not call external Obsidian CLI")

    monkeypatch.setattr(adapter, "run", fail_run)

    adapter.create_or_update_note("wiki/sources/demo.md", "# Demo\n")
    adapter.append_note("wiki/log.md", "- appended\n")

    assert (adapter.config.wiki_dir / "sources" / "demo.md").read_text(encoding="utf-8") == "# Demo\n"
    assert "- appended\n" in (adapter.config.wiki_dir / "log.md").read_text(encoding="utf-8")


def test_append_note_appends_wiki_log_with_fallback(tmp_path):
    adapter = _adapter(tmp_path)

    adapter.append_note("wiki/log.md", "- appended\n")

    assert "- appended\n" in (adapter.config.wiki_dir / "log.md").read_text(encoding="utf-8")


def test_create_or_update_note_rejects_raw_write(tmp_path):
    adapter = _adapter(tmp_path)

    with pytest.raises(PermissionError, match="raw/ is read-only"):
        adapter.create_or_update_note("raw/sample.md", "nope")


def test_list_files_lists_wiki_markdown_files_with_fallback(tmp_path):
    adapter = _adapter(tmp_path)

    files = adapter.list_files("wiki")

    assert "wiki/index.md" in files


def test_search_defaults_to_wiki_folder_with_fallback(tmp_path):
    adapter = _adapter(tmp_path)

    matches = adapter.search("Agent")

    assert "wiki/index.md" in matches
    assert "raw/sample.md" not in matches


def test_links_extracts_wikilinks_from_note(tmp_path):
    adapter = _adapter(tmp_path)

    links = adapter.links("wiki/index.md")

    assert links == ["AI Agent"]


def test_cli_path_parser_filters_paths_outside_vault(tmp_path):
    adapter = _adapter(tmp_path)
    inside = adapter.config.wiki_dir / "index.md"
    outside = tmp_path / "outside.md"

    paths = adapter._parse_cli_paths(
        f"wiki/index.md\n{inside}\n../outside.md\n{outside}\n"
    )

    assert paths == ["wiki/index.md", "wiki/index.md"]
