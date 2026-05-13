from pathlib import Path
from shutil import copytree
from unittest.mock import MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot_obsidian_wiki.mcp_server import run_obsidian_eval_tool, run_obsidian_wiki_tool


def test_obsidian_wiki_mcp_tool_calls_api(monkeypatch):
    calls = {}

    def fake_run(vault_path, request, execute=False):
        calls["vault_path"] = vault_path
        calls["request"] = request
        calls["execute"] = execute
        return "ok"

    monkeypatch.setattr("nanobot_obsidian_wiki.api.run_obsidian_wiki_request", fake_run)
    monkeypatch.setattr("nanobot_obsidian_wiki.mcp_server.run_obsidian_wiki_request", fake_run)

    result = run_obsidian_wiki_tool(
        vault_path="vault",
        request="请对 wiki 做一次 Lint",
        execute=True,
    )

    assert result == "ok"
    assert calls == {
        "vault_path": "vault",
        "request": "请对 wiki 做一次 Lint",
        "execute": True,
    }


def test_obsidian_wiki_mcp_tool_default_dry_run_does_not_write(tmp_path):
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)

    result = run_obsidian_wiki_tool(
        vault_path=str(vault),
        request="请基于 raw/sample.md 进行 Ingest",
    )

    assert "Ingest dry-run plan" in result
    assert not (vault / "wiki" / "sources" / "sample.md").exists()


def test_obsidian_eval_mcp_tool_runs_default_cases(tmp_path):
    vault = tmp_path / "sample_vault"
    copytree(Path("tests/fixtures/sample_vault"), vault)

    result = run_obsidian_eval_tool(vault_path=str(vault))

    assert "# Agent Evaluation Report" in result
    assert "pass_rate: 100.0%" in result


def test_agent_loop_does_not_register_obsidian_wiki_builtin_tool(tmp_path):
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    provider.generation.max_tokens = 4096

    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
    )

    assert not loop.tools.has("obsidian_wiki")
