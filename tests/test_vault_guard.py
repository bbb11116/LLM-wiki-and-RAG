from pathlib import Path

import pytest

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.vault_guard import VaultGuard


def test_wiki_agent_config_validates_sample_vault():
    config = WikiAgentConfig.from_vault(Path("tests/fixtures/sample_vault"))

    assert config.vault_path.is_absolute()
    assert config.schema_path.name == "TheSchema.md"
    assert config.raw_dir.name == "raw"
    assert config.wiki_dir.name == "wiki"
    assert config.log_file.name == "log.md"


def test_vault_guard_check_sample_vault():
    guard = VaultGuard(Path("tests/fixtures/sample_vault"))

    status = guard.check()

    assert status.ok
    assert status.schema_path.name == "TheSchema.md"
    assert status.raw_dir.name == "raw"
    assert status.wiki_dir.name == "wiki"


def test_vault_guard_allows_reading_raw_sample():
    guard = VaultGuard(Path("tests/fixtures/sample_vault"))

    resolved = guard.assert_can_read("raw/sample.md")

    assert resolved.name == "sample.md"
    assert resolved.is_file()


def test_vault_guard_allows_wiki_write_path():
    guard = VaultGuard(Path("tests/fixtures/sample_vault"))

    resolved = guard.assert_can_write("wiki/sources/demo.md")

    assert resolved.name == "demo.md"
    assert "wiki" in resolved.parts


def test_vault_guard_blocks_raw_write():
    guard = VaultGuard(Path("tests/fixtures/sample_vault"))

    with pytest.raises(PermissionError, match="raw/ is read-only"):
        guard.assert_can_write("raw/sample.md")


def test_vault_guard_blocks_path_traversal():
    guard = VaultGuard(Path("tests/fixtures/sample_vault"))

    with pytest.raises(PermissionError, match="Path traversal"):
        guard.assert_can_read("../outside.md")


def test_vault_guard_blocks_write_outside_vault(tmp_path):
    guard = VaultGuard(Path("tests/fixtures/sample_vault"))
    outside = tmp_path / "outside.md"

    with pytest.raises(PermissionError, match="outside the configured vault"):
        guard.assert_can_write(outside)
