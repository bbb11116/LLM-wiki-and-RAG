"""Adapter for the official Obsidian CLI with safe Python fallbacks."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import CLIResult
from nanobot_obsidian_wiki.utils.frontmatter import extract_wikilinks
from nanobot_obsidian_wiki.vault_guard import VaultGuard


class ObsidianCLIAdapter:
    """Wrap Obsidian CLI access and keep all fallback file I/O behind VaultGuard."""

    _FALLBACK_WARNING = (
        "Obsidian CLI is unavailable; Python file fallback will be used for basic read/write "
        "operations."
    )

    def __init__(self, config: WikiAgentConfig, guard: VaultGuard):
        self.config = config
        self.guard = guard
        self.last_warning: str | None = None
        self._available: bool | None = None

    def check_available(self) -> bool:
        if self._available is not None:
            return self._available

        result = self.run(["--help"], timeout=2)
        self._available = result.returncode == 0
        if not self._available:
            detail = (result.stderr or result.stdout).strip()
            self.last_warning = self._FALLBACK_WARNING if not detail else f"{self._FALLBACK_WARNING} {detail}"
        return self._available

    def run(self, args: list[str], timeout: int = 30) -> CLIResult:
        command = [self.config.obsidian_cmd, *args]
        try:
            completed = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                encoding="utf-8",
                cwd=self.config.vault_path,
            )
            return CLIResult(
                args=command,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        except FileNotFoundError:
            return CLIResult(
                args=command,
                returncode=127,
                stdout="",
                stderr=f"{self._FALLBACK_WARNING} Command not found: {self.config.obsidian_cmd}",
            )
        except subprocess.TimeoutExpired as exc:
            return CLIResult(
                args=command,
                returncode=124,
                stdout=exc.stdout or "",
                stderr=f"Obsidian CLI timed out after {timeout} seconds.",
            )

    def read_note(self, path: str) -> str:
        resolved = self.guard.assert_can_read(path)
        relative = self._relative_posix(resolved)

        if self.check_available():
            result = self.run(["read", f"path={relative}"])
            if result.returncode == 0:
                return result.stdout
            self.last_warning = f"Obsidian CLI read failed; using Python fallback. {result.stderr}"

        return resolved.read_text(encoding="utf-8")

    def create_or_update_note(self, path: str, content: str) -> None:
        resolved = self.guard.assert_can_write(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    def append_note(self, path: str, content: str) -> None:
        resolved = self.guard.assert_can_write(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("a", encoding="utf-8") as handle:
            handle.write(content)

    def list_files(self, folder: str = "wiki") -> list[str]:
        folder_path = self.guard.assert_can_read(folder)

        if self.check_available():
            result = self.run(["files", f"folder={folder}"])
            if result.returncode == 0:
                return self._parse_cli_paths(result.stdout)
            self.last_warning = f"Obsidian CLI files failed; using Python fallback. {result.stderr}"

        return sorted(
            self._relative_posix(path)
            for path in folder_path.rglob("*.md")
            if path.is_file()
        )

    def search(self, query: str, folder: str = "wiki") -> list[str]:
        folder_path = self.guard.assert_can_read(folder)

        if self.check_available():
            result = self.run(["search", f"query={query}", f"folder={folder}"])
            if result.returncode == 0:
                return self._parse_cli_paths(result.stdout)
            self.last_warning = f"Obsidian CLI search failed; using Python fallback. {result.stderr}"

        matches: list[str] = []
        for path in folder_path.rglob("*.md"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if query.lower() in text.lower():
                matches.append(self._relative_posix(path))
        return sorted(matches)

    def links(self, path: str) -> list[str]:
        return extract_wikilinks(self.read_note(path))

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.append_note("wiki/log.md", f"- {timestamp} | {message}\n")

    def _relative_posix(self, path: Path) -> str:
        return path.resolve().relative_to(self.config.vault_path).as_posix()

    def _parse_cli_paths(self, stdout: str) -> list[str]:
        paths: list[str] = []
        for line in stdout.splitlines():
            value = line.strip()
            if value:
                try:
                    relative = self.guard.normalize_vault_relative_path(value)
                except PermissionError:
                    continue
                paths.append(relative.as_posix())
        return paths


# Backward-compatible name for first-stage imports, if any downstream code used it.
ObsidianCLI = ObsidianCLIAdapter
