"""Append-only wiki log helper."""

from __future__ import annotations

from datetime import datetime, timezone

from nanobot_obsidian_wiki.vault_guard import VaultGuard


def format_log_entry(action: str, target: str) -> str:
    timestamp = datetime.now(timezone.utc).isoformat()
    return f"- {timestamp} | {action} | {target}\n"


def append_wiki_log(guard: VaultGuard, action: str, target: str, *, execute: bool) -> str:
    entry = format_log_entry(action, target)
    if not execute:
        return entry
    log_path = guard.resolve_wiki_write("wiki/log.md")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    return entry

