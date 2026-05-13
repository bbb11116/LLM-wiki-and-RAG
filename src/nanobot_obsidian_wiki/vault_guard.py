"""Vault safety checks for raw/wiki access."""

from __future__ import annotations

from pathlib import Path

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import VaultStatus


class VaultGuard:
    """Enforce the Obsidian wiki vault boundary and write policy."""

    def __init__(self, config: WikiAgentConfig | str | Path):
        if isinstance(config, WikiAgentConfig):
            self.config = config
        else:
            self.config = WikiAgentConfig.from_vault(config)

    def check(self) -> VaultStatus:
        """Return the already validated vault layout as a status object."""

        return VaultStatus(
            vault=self.config.vault_path,
            schema_path=self.config.schema_path,
            raw_dir=self.config.raw_dir,
            wiki_dir=self.config.wiki_dir,
            ok=True,
            missing=[],
        )

    def require_valid(self) -> VaultStatus:
        return self.check()

    def normalize_vault_relative_path(self, path: str | Path) -> Path:
        """Normalize a path to a vault-relative path and reject traversal."""

        candidate = Path(path).expanduser()
        if ".." in candidate.parts:
            raise PermissionError(f"Path traversal is not allowed inside the vault: {path}")

        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.config.vault_path / candidate).resolve()

        if not _is_under(resolved, self.config.vault_path):
            raise PermissionError(f"Path is outside the configured vault: {path}")

        return resolved.relative_to(self.config.vault_path)

    def resolve_vault_path(self, path: str | Path) -> Path:
        """Return an absolute resolved path inside the vault."""

        relative = self.normalize_vault_relative_path(path)
        resolved = (self.config.vault_path / relative).resolve()
        if not _is_under(resolved, self.config.vault_path):
            raise PermissionError(f"Path is outside the configured vault: {path}")
        return resolved

    def is_under_raw(self, path: str | Path) -> bool:
        try:
            return _is_under(self.resolve_vault_path(path), self.config.raw_dir)
        except PermissionError:
            return False

    def is_under_wiki(self, path: str | Path) -> bool:
        try:
            return _is_under(self.resolve_vault_path(path), self.config.wiki_dir)
        except PermissionError:
            return False

    def assert_can_read(self, path: str | Path) -> Path:
        """Allow reads from raw/ and wiki/ only."""

        resolved = self.resolve_vault_path(path)
        if not (self.is_under_raw(resolved) or self.is_under_wiki(resolved)):
            raise PermissionError(f"Reads are only allowed under raw/ or wiki/: {path}")
        if not resolved.exists():
            raise FileNotFoundError(f"File or directory does not exist: {resolved}")
        if resolved.is_file() and _size_mb(resolved) > self.config.max_file_size_mb:
            raise PermissionError(
                f"File is larger than the configured limit "
                f"({self.config.max_file_size_mb} MB): {resolved}"
            )
        return resolved

    def assert_can_write(self, path: str | Path) -> Path:
        """Allow writes only under wiki/."""

        resolved = self.resolve_vault_path(path)
        self.assert_no_write_to_raw(resolved)
        if not self.is_under_wiki(resolved):
            raise PermissionError(f"Writes are only allowed under wiki/: {path}")
        return resolved

    def assert_no_write_to_raw(self, path: str | Path) -> None:
        if self.is_under_raw(path):
            raise PermissionError(f"raw/ is read-only and cannot be modified: {path}")

    def resolve_read(self, path: str | Path) -> Path:
        """Backward-compatible alias for first-stage workflow code."""

        return self.assert_can_read(path)

    def resolve_wiki_write(self, path: str | Path) -> Path:
        """Backward-compatible alias for first-stage workflow code."""

        return self.assert_can_write(path)


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _size_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)
