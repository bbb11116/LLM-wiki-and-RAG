"""Batch compile stable raw documents into structured LLM Wiki pages."""

from __future__ import annotations

from dataclasses import dataclass

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import WikiSchema
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.vault_guard import VaultGuard
from nanobot_obsidian_wiki.workflows.ingest import IngestWorkflow


@dataclass(frozen=True, slots=True)
class CompileCandidate:
    raw_path: str
    reason: str
    target_exists: bool


class WikiCompileWorkflow:
    """Select stable raw documents and compile them into the curated Wiki."""

    _SUPPORTED_SUFFIXES = {".md", ".txt"}

    def __init__(
        self,
        config: WikiAgentConfig,
        schema: WikiSchema,
        guard: VaultGuard,
        obsidian: ObsidianCLIAdapter,
    ) -> None:
        self.config = config
        self.schema = schema
        self.guard = guard
        self.obsidian = obsidian
        self.ingest = IngestWorkflow(config, schema, guard, obsidian)

    def find_candidates(
        self,
        *,
        limit: int = 20,
        include_existing: bool = False,
    ) -> list[CompileCandidate]:
        candidates: list[CompileCandidate] = []
        for path in sorted(self.config.raw_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self._SUPPORTED_SUFFIXES:
                continue
            raw_relative = path.relative_to(self.config.vault_path).as_posix()
            target = self.config.wiki_dir / "sources" / f"{path.stem}.md"
            target_exists = target.exists()
            if target_exists and not include_existing:
                continue
            if _looks_dynamic(raw_relative, path.read_text(encoding="utf-8", errors="replace")):
                continue
            candidates.append(
                CompileCandidate(
                    raw_path=raw_relative,
                    reason="stable raw document selected for LLM Wiki compilation",
                    target_exists=target_exists,
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    def run(
        self,
        *,
        execute: bool = False,
        limit: int = 20,
        include_existing: bool = False,
    ) -> str:
        candidates = self.find_candidates(limit=limit, include_existing=include_existing)
        if not candidates:
            return (
                "# Wiki Compile Plan\n\n"
                "- candidates: 0\n"
                "- status: no stable raw documents need compilation\n"
            )

        lines = [
            "# Wiki Compile Plan" if not execute else "# Wiki Compile Result",
            "",
            f"- candidates: {len(candidates)}",
            f"- execute: {str(execute).lower()}",
            "",
        ]
        for candidate in candidates:
            lines.extend(
                [
                    f"## {candidate.raw_path}",
                    "",
                    f"- reason: {candidate.reason}",
                    f"- target_exists: {str(candidate.target_exists).lower()}",
                    "",
                ]
            )
            if execute:
                lines.append(self.ingest.execute(candidate.raw_path, execute=True))
                lines.append("")
            else:
                lines.append(self.ingest.execute(candidate.raw_path, execute=False))
                lines.append("")
        return "\n".join(lines).rstrip()


def _looks_dynamic(raw_path: str, content: str) -> bool:
    text = f"{raw_path}\n{content}".lower()
    dynamic_markers = {
        "temporary",
        "latest",
        "today",
        "yesterday",
        "临时",
        "最新",
        "今天",
        "昨天",
        "公告",
        "工单",
        "日报",
        "周报",
    }
    return any(marker in text for marker in dynamic_markers)
