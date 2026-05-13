"""Path safety helpers."""

from __future__ import annotations

from pathlib import Path


def resolve_under(root: Path, candidate: str | Path) -> Path:
    """Resolve a candidate path under root and reject path traversal."""

    base = root.expanduser().resolve()
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()
    if not is_relative_to(resolved, base):
        raise PermissionError(f"Path is outside vault: {candidate}")
    return resolved


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

