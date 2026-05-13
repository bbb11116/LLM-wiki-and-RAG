"""Wiki lint workflow for schema-driven Obsidian vaults."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import WikiSchema
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.utils.frontmatter import (
    dump_frontmatter,
    ensure_required_fields,
    extract_wikilinks,
    parse_frontmatter,
)
from nanobot_obsidian_wiki.vault_guard import VaultGuard

VALID_PAGE_TYPES = {"source", "entity", "concept", "comparison", "overview"}


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    path: str
    message: str
    severity: str = "medium"
    target: str | None = None


class LintWorkflow:
    """Read-only wiki health checks plus optional low-risk frontmatter fixes."""

    def __init__(
        self,
        config: WikiAgentConfig,
        schema: WikiSchema,
        guard: VaultGuard,
        obsidian: ObsidianCLIAdapter,
    ):
        self.config = config
        self.schema = schema
        self.guard = guard
        self.obsidian = obsidian

    def scan_wiki_files(self) -> list[str]:
        return self.obsidian.list_files("wiki")

    def check_frontmatter(self, files: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for path in files:
            content = self.obsidian.read_note(path)
            has_frontmatter = content.startswith("---\n")
            metadata, _body = parse_frontmatter(content)
            if not has_frontmatter:
                issues.append(Issue("missing_frontmatter", path, "Missing YAML frontmatter."))
                continue
            page_type = metadata.get("type")
            if page_type is None:
                issues.append(Issue("missing_type", path, "Missing frontmatter field: type."))
            elif page_type not in VALID_PAGE_TYPES:
                issues.append(
                    Issue(
                        "invalid_type",
                        path,
                        f"Invalid page type: {page_type}.",
                        severity="high",
                    )
                )
            if not metadata.get("summary"):
                issues.append(Issue("missing_summary", path, "Missing frontmatter field: summary."))
            if "sources" not in metadata:
                issues.append(Issue("missing_sources", path, "Missing frontmatter field: sources."))
            if "updated" not in metadata:
                issues.append(Issue("missing_updated", path, "Missing frontmatter field: updated."))
        return issues

    def check_unresolved_links(self, files: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for path in files:
            content = self.obsidian.read_note(path)
            for link in extract_wikilinks(content):
                if not self._resolve_link(link, files):
                    issues.append(
                        Issue(
                            "unresolved_link",
                            path,
                            f"Unresolved wikilink: [[{link}]].",
                            severity="high",
                            target=link,
                        )
                    )
        return issues

    def check_deadend_pages(self, files: list[str]) -> list[Issue]:
        issues: list[Issue] = []
        for path in files:
            content = self.obsidian.read_note(path)
            if not extract_wikilinks(content):
                issues.append(Issue("deadend_page", path, "Page has no outgoing wikilinks.", "low"))
        return issues

    def check_orphan_pages(self, files: list[str]) -> list[Issue]:
        linked: set[str] = set()
        for path in files:
            content = self.obsidian.read_note(path)
            for link in extract_wikilinks(content):
                resolved = self._resolve_link(link, files)
                if resolved and resolved.startswith("wiki/"):
                    linked.add(resolved)

        protected = {"wiki/index.md", "wiki/log.md"}
        return [
            Issue("orphan_page", path, "Page is not linked from any other wiki page.", "medium")
            for path in files
            if path not in linked and path not in protected
        ]

    def generate_report(self, execute: bool = False) -> str:
        files = self.scan_wiki_files()
        frontmatter = self.check_frontmatter(files)
        unresolved = self.check_unresolved_links(files)
        deadends = self.check_deadend_pages(files)
        orphans = self.check_orphan_pages(files)
        all_issues = frontmatter + unresolved + deadends + orphans

        lines = [
            f"# Wiki Lint Report - {date.today().isoformat()}",
            "",
            "## 总览",
            "",
            f"- 扫描页面数：{len(files)}",
            f"- 缺失 frontmatter：{_count(frontmatter, 'missing_frontmatter')}",
            f"- 缺失 summary：{_count(frontmatter, 'missing_summary')}",
            f"- 未解析链接：{len(unresolved)}",
            f"- 孤立页面：{len(orphans)}",
            f"- 无出链页面：{len(deadends)}",
            "",
            "## 严重问题",
            "",
            *_render_issues([issue for issue in all_issues if issue.severity == "high"]),
            "",
            "## 中等问题",
            "",
            *_render_issues([issue for issue in all_issues if issue.severity == "medium"]),
            "",
            "## 低风险修复建议",
            "",
            "- 可为缺少 frontmatter 的页面补充模板 frontmatter。",
            '- 可为缺少 summary 的页面填入 "TODO: add summary"。',
            "- execute 模式仅执行上述低风险修复，并追加 wiki/log.md。",
            "",
            "## 高风险操作，不自动执行",
            "",
            "- 不删除页面。",
            "- 不移动、重命名、合并或拆分页面。",
            "- 不大规模改写正文。",
            "- 不修改 raw/。",
            "",
            "## 建议下一步",
            "",
            "- 先处理未解析链接和孤立页面。",
            "- 对 TODO summary 进行人工确认或后续 LLM 精炼。",
        ]
        if execute:
            lines.extend(["", "## Execute 结果", "", self.execute_low_risk_fixes()])
        return "\n".join(lines)

    def execute_low_risk_fixes(self) -> str:
        files = self.scan_wiki_files()
        changed: list[str] = []
        for path in files:
            content = self.obsidian.read_note(path)
            has_frontmatter = content.startswith("---\n")
            metadata, body = parse_frontmatter(content)
            if not has_frontmatter:
                fixed = ensure_required_fields({}, _infer_page_type(path))
                fixed["summary"] = "TODO: add summary"
                self.obsidian.create_or_update_note(path, dump_frontmatter(fixed, content))
                changed.append(path)
                continue

            if not metadata.get("summary"):
                metadata = dict(metadata)
                metadata["summary"] = "TODO: add summary"
                self.obsidian.create_or_update_note(path, dump_frontmatter(metadata, body))
                changed.append(path)

        self.obsidian.append_log(
            "Lint low-risk fixes applied"
            if changed
            else "Lint low-risk fixes checked; no changes needed"
        )
        if not changed:
            return "No low-risk fixes were needed. Appended wiki/log.md."
        return "Applied low-risk fixes:\n" + "\n".join(f"- {path}" for path in changed)

    def _resolve_link(self, link: str, wiki_files: list[str]) -> str | None:
        target = link.strip().split("#", 1)[0].removesuffix(".md")
        if not target:
            return None

        candidates: list[str] = []
        if target.startswith("wiki/"):
            candidates.append(f"{target}.md")
        elif target.startswith("raw/"):
            raw_candidate = f"{target}.md"
            try:
                raw_path = self.guard.resolve_vault_path(raw_candidate)
            except PermissionError:
                raw_path = None
            if raw_path and raw_path.is_file():
                return raw_candidate
        elif "/" in target:
            candidates.append(f"wiki/{target}.md")
            candidates.append(f"{target}.md")
        else:
            candidates.extend(path for path in wiki_files if path.removesuffix(".md").endswith(f"/{target}"))
            candidates.append(f"wiki/{target}.md")

        for candidate in candidates:
            normalized = candidate.replace("\\", "/")
            if normalized in wiki_files:
                return normalized
        target_key = _link_key(target)
        if target_key:
            for path in wiki_files:
                stem = path.removesuffix(".md").rsplit("/", 1)[-1]
                if _link_key(stem) == target_key:
                    return path
        return None


def _count(issues: list[Issue], code: str) -> int:
    return Counter(issue.code for issue in issues)[code]


def _render_issues(issues: list[Issue]) -> list[str]:
    if not issues:
        return ["- 无"]
    return [f"- `{issue.path}` [{issue.code}] {issue.message}" for issue in issues]


def _infer_page_type(path: str) -> str:
    if path.startswith("wiki/sources/"):
        return "source"
    if path.startswith("wiki/entities/"):
        return "entity"
    if path.startswith("wiki/concepts/"):
        return "concept"
    if path.startswith("wiki/comparisons/"):
        return "comparison"
    return "overview"


def _link_key(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", value.lower())
    return "-".join(words)
