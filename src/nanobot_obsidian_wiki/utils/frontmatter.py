"""Markdown frontmatter and wikilink utilities."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import yaml


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from a Markdown document."""

    if not markdown.startswith("---\n"):
        return {}, markdown

    marker = "\n---\n"
    end = markdown.find(marker, 4)
    if end == -1:
        return {}, markdown

    raw_metadata = markdown[4:end]
    body = markdown[end + len(marker):]
    if body.startswith("\n"):
        body = body[1:]
    try:
        parsed = yaml.safe_load(raw_metadata) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Invalid YAML frontmatter: top-level value must be a mapping.")
    return parsed, body


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    """Render metadata and body as a Markdown document with YAML frontmatter."""

    yaml_text = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
    clean_body = body.lstrip("\n")
    return f"---\n{yaml_text}\n---\n\n{clean_body}"


def ensure_required_fields(metadata: dict[str, Any], page_type: str) -> dict[str, Any]:
    """Return metadata with the required wiki fields filled in."""

    enriched = dict(metadata)
    enriched.setdefault("type", page_type)
    enriched.setdefault("tags", [])
    enriched.setdefault("summary", "")
    enriched.setdefault("sources", [])
    enriched.setdefault("updated", date.today().isoformat())
    return enriched


def extract_wikilinks(markdown: str) -> list[str]:
    """Extract Obsidian wikilink targets from Markdown.

    This first version intentionally includes embeds such as ``![[image.png]]``
    because they share the same target syntax and may be useful for later linting.
    """

    links: list[str] = []
    for match in re.finditer(r"!?\[\[([^\]]+)\]\]", markdown):
        raw = match.group(1).strip()
        if not raw:
            continue
        target = raw.split("|", 1)[0].strip()
        if target:
            links.append(target)
    return links
