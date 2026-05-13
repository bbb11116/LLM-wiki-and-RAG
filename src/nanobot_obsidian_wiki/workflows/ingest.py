"""Ingest workflow for turning raw Markdown/Text files into structured wiki pages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import WikiSchema, WritePlan
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.utils.frontmatter import dump_frontmatter, extract_wikilinks
from nanobot_obsidian_wiki.vault_guard import VaultGuard


@dataclass(frozen=True, slots=True)
class PlannedPage:
    page_type: str
    title: str
    path: Path
    summary: str


class IngestWorkflow:
    """Deterministic ingest workflow.

    This stage intentionally avoids LLM calls, OCR, PDF parsing, RAG, and embeddings.
    """

    _SUPPORTED_SUFFIXES = {".md", ".txt"}

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

    def build_plan(self, raw_path: str, user_focus: str | None = None) -> WritePlan:
        raw_file = self._resolve_raw_file(raw_path)
        raw_content = raw_file.read_text(encoding="utf-8")
        planned_pages = self._planned_pages(raw_file, raw_content, user_focus=user_focus)

        files_to_create: list[str] = []
        files_to_update: list[str] = []
        for page in planned_pages:
            relative = self._relative_posix(page.path)
            if page.path.exists():
                files_to_update.append(relative)
            else:
                files_to_create.append(relative)

        warnings = ["dry-run 默认不写入"]
        if user_focus:
            warnings.append(f"用户关注点将作为候选概念写入草稿，并可供后续 LLM 精炼：{user_focus}")

        return WritePlan(
            title=f"Ingest {self._relative_posix(raw_file)}",
            summary=(
                f"将 {self._relative_posix(raw_file)} 沉淀为 source、concept、entity "
                "结构化页面"
            ),
            files_to_create=files_to_create,
            files_to_update=files_to_update,
            files_to_append=["wiki/index.md", "wiki/log.md"],
            warnings=warnings,
            requires_confirmation=True,
        )

    def render_source_summary(self, raw_path: str, raw_content: str) -> str:
        raw_file = self._resolve_raw_file(raw_path)
        planned_pages = self._planned_pages(raw_file, raw_content)
        concepts = [page for page in planned_pages if page.page_type == "concept"]
        entities = [page for page in planned_pages if page.page_type == "entity"]
        return self._render_source_page(raw_file, raw_content, concepts, entities)

    def _render_source_page(
        self,
        raw_file: Path,
        raw_content: str,
        concepts: list[PlannedPage],
        entities: list[PlannedPage],
    ) -> str:
        raw_relative = self._relative_posix(raw_file)
        title = raw_file.stem
        today = date.today().isoformat()
        excerpt = _excerpt_as_quote(raw_content)
        metadata = {
            "type": "source",
            "tags": ["llm-wiki"],
            "summary": f"基于 {raw_relative} 的来源摘要页",
            "sources": [raw_relative],
            "updated": today,
        }
        concept_links = _page_link_bullets(concepts, self.config.wiki_dir)
        entity_links = _page_link_bullets(entities, self.config.wiki_dir)
        key_points = _key_point_bullets(raw_content)

        body = (
            f"# {title}\n\n"
            "## 来源信息\n\n"
            f"- 原始文件：[[{raw_relative}]]\n"
            f"- 导入时间：{today}\n\n"
            "## 核心要点\n\n"
            f"{key_points}\n\n"
            "## 关键内容摘录\n\n"
            f"{excerpt}\n\n"
            "## 关联实体\n\n"
            f"{entity_links}\n\n"
            "## 关联概念\n\n"
            f"{concept_links}\n\n"
            "## 待确认问题\n\n"
            "- TODO\n"
        )
        return dump_frontmatter(metadata, body)

    def execute(
        self,
        raw_path: str,
        user_focus: str | None = None,
        execute: bool = False,
    ) -> str:
        plan = self.build_plan(raw_path, user_focus=user_focus)
        if not execute or self.config.dry_run:
            return self._render_plan(plan, executed=False)

        raw_file = self._resolve_raw_file(raw_path)
        raw_relative = self._relative_posix(raw_file)
        raw_content = raw_file.read_text(encoding="utf-8")
        planned_pages = self._planned_pages(raw_file, raw_content, user_focus=user_focus)
        concepts = [page for page in planned_pages if page.page_type == "concept"]
        entities = [page for page in planned_pages if page.page_type == "entity"]

        for page in planned_pages:
            relative = self._relative_posix(page.path)
            if page.page_type == "source":
                content = self._render_source_page(raw_file, raw_content, concepts, entities)
            elif page.page_type == "concept":
                content = self._render_concept_page(page, raw_file, raw_content, entities)
            elif page.page_type == "entity":
                content = self._render_entity_page(page, raw_file, raw_content, concepts)
            else:
                continue
            self.obsidian.create_or_update_note(relative, content)

        self._append_index_links(raw_relative, planned_pages)
        written = [self._relative_posix(page.path) for page in planned_pages]
        self.obsidian.append_log(f"Ingested {raw_relative} -> {', '.join(written)}")

        wrote_lines = "\n".join(f"- wrote: {path}" for path in written)
        return (
            "Ingest executed.\n"
            f"- source: {raw_relative}\n"
            f"{wrote_lines}\n"
            "- updated: wiki/index.md\n"
            "- appended: wiki/log.md"
        )

    def _resolve_raw_file(self, raw_path: str) -> Path:
        resolved = self.guard.assert_can_read(raw_path)
        if not self.guard.is_under_raw(resolved):
            raise PermissionError(f"Ingest only accepts files under raw/: {raw_path}")
        if not resolved.is_file():
            raise FileNotFoundError(f"Raw source is not a file: {resolved}")
        if resolved.suffix.lower() == ".pdf":
            raise ValueError("不支持 PDF，请先转换为 Markdown")
        if resolved.suffix.lower() not in self._SUPPORTED_SUFFIXES:
            allowed = ", ".join(sorted(self._SUPPORTED_SUFFIXES))
            raise ValueError(f"Unsupported raw file type: {resolved.suffix}. Supported: {allowed}")
        return resolved

    def _source_page_for_raw(self, raw_file: Path) -> Path:
        return self._page_dir("source") / f"{raw_file.stem}.md"

    def _planned_pages(
        self,
        raw_file: Path,
        raw_content: str,
        user_focus: str | None = None,
    ) -> list[PlannedPage]:
        raw_relative = self._relative_posix(raw_file)
        title = _raw_title(raw_file, raw_content)
        source_page = PlannedPage(
            page_type="source",
            title=raw_file.stem,
            path=self._source_page_for_raw(raw_file),
            summary=f"基于 {raw_relative} 的来源摘要页",
        )

        concepts = self._pages_for_terms(
            "concept",
            _extract_concept_terms(title, raw_content, user_focus=user_focus),
            raw_file,
            f"从 {raw_relative} 提取的概念",
        )
        entities = self._pages_for_terms(
            "entity",
            _extract_entity_terms(title, raw_content, concept_terms=[page.title for page in concepts]),
            raw_file,
            f"从 {raw_relative} 提取的实体",
        )
        return [source_page, *concepts, *entities]

    def _pages_for_terms(
        self,
        page_type: str,
        terms: list[str],
        raw_file: Path,
        summary_prefix: str,
    ) -> list[PlannedPage]:
        pages: list[PlannedPage] = []
        seen_slugs: set[str] = set()
        for term in terms:
            slug = _slugify(term) or raw_file.stem
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            pages.append(
                PlannedPage(
                    page_type=page_type,
                    title=term,
                    path=self._page_dir(page_type) / f"{slug}.md",
                    summary=f"{summary_prefix}：{term}",
                )
            )
        return pages

    def _page_dir(self, page_type: str) -> Path:
        default_dir = {
            "source": "wiki/sources",
            "entity": "wiki/entities",
            "concept": "wiki/concepts",
        }[page_type]
        configured = Path(self.schema.page_type_dirs.get(page_type, default_dir))
        if configured.parts and configured.parts[0] == self.schema.wiki_dir_name:
            return self.config.vault_path / configured
        return self.config.wiki_dir / configured

    def _render_concept_page(
        self,
        page: PlannedPage,
        raw_file: Path,
        raw_content: str,
        entities: list[PlannedPage],
    ) -> str:
        raw_relative = self._relative_posix(raw_file)
        source_link = _display_link(self._source_page_for_raw(raw_file), self.config.wiki_dir)
        metadata = _metadata("concept", page.summary, raw_relative)
        body = (
            f"# {page.title}\n\n"
            "## 概念说明\n\n"
            f"- 该概念由 Ingest 从 [[{raw_relative}]] 中自动提取。\n"
            f"- 来源摘要页：[[{source_link}]]\n"
            "- 当前内容为确定性草稿，适合后续人工确认或 LLM 精炼。\n\n"
            "## 来源摘录\n\n"
            f"{_excerpt_as_quote(raw_content, max_chars=600)}\n\n"
            "## 关联实体\n\n"
            f"{_page_link_bullets(entities, self.config.wiki_dir)}\n\n"
            "## 待整理\n\n"
            "- TODO: 补充定义、边界、例子和反例。\n"
        )
        return dump_frontmatter(metadata, body)

    def _render_entity_page(
        self,
        page: PlannedPage,
        raw_file: Path,
        raw_content: str,
        concepts: list[PlannedPage],
    ) -> str:
        raw_relative = self._relative_posix(raw_file)
        source_link = _display_link(self._source_page_for_raw(raw_file), self.config.wiki_dir)
        metadata = _metadata("entity", page.summary, raw_relative)
        body = (
            f"# {page.title}\n\n"
            "## 实体说明\n\n"
            f"- 该实体由 Ingest 从 [[{raw_relative}]] 中自动识别。\n"
            f"- 来源摘要页：[[{source_link}]]\n"
            "- 当前内容为确定性草稿，适合后续人工确认或 LLM 精炼。\n\n"
            "## 来源摘录\n\n"
            f"{_excerpt_as_quote(raw_content, max_chars=600)}\n\n"
            "## 关联概念\n\n"
            f"{_page_link_bullets(concepts, self.config.wiki_dir)}\n\n"
            "## 待整理\n\n"
            "- TODO: 补充实体背景、相关项目、人物、组织或系统关系。\n"
        )
        return dump_frontmatter(metadata, body)

    def _append_index_links(self, raw_relative: str, pages: list[PlannedPage]) -> None:
        index_path = "wiki/index.md"
        index_content = self.obsidian.read_note(index_path)
        additions: list[str] = []
        for section, page_type, description in (
            ("Sources", "source", "来源摘要页"),
            ("Concepts", "concept", "自动提取概念"),
            ("Entities", "entity", "自动识别实体"),
        ):
            bullets: list[str] = []
            for page in pages:
                if page.page_type != page_type:
                    continue
                link_target = _display_link(page.path, self.config.wiki_dir)
                if f"[[{link_target}]]" in index_content or f"[[{link_target}]]" in "\n".join(additions):
                    continue
                if page_type == "source":
                    bullet = f"- [[{link_target}]] - 基于 {raw_relative} 的{description}"
                else:
                    bullet = f"- [[{link_target}]] - 基于 {raw_relative} 的{description}：{page.title}"
                bullets.append(bullet)

            if not bullets:
                continue
            if f"## {section}" not in index_content and f"## {section}" not in "\n".join(additions):
                additions.append(f"\n\n## {section}\n\n" + "\n".join(bullets) + "\n")
            else:
                additions.append("\n" + "\n".join(bullets) + "\n")

        if additions:
            self.obsidian.append_note(index_path, "".join(additions))

    def _append_index_link(self, raw_relative: str, target_relative: str) -> None:
        """Backward-compatible wrapper for callers that only add the source page."""

        page = PlannedPage(
            page_type="source",
            title=Path(target_relative).stem,
            path=self.config.vault_path / target_relative,
            summary=f"基于 {raw_relative} 的来源摘要页",
        )
        self._append_index_links(raw_relative, [page])

    def _render_plan(self, plan: WritePlan, *, executed: bool) -> str:
        lines = [
            "Ingest dry-run plan" if not executed else "Ingest write plan",
            f"title: {plan.title}",
            f"summary: {plan.summary}",
        ]
        lines.extend(_section("files_to_create", plan.files_to_create))
        lines.extend(_section("files_to_update", plan.files_to_update))
        lines.extend(_section("files_to_append", plan.files_to_append))
        lines.extend(_section("warnings", plan.warnings))
        lines.append(f"requires_confirmation: {str(plan.requires_confirmation).lower()}")
        return "\n".join(lines)

    def _relative_posix(self, path: Path) -> str:
        return path.resolve().relative_to(self.config.vault_path).as_posix()


def _section(name: str, values: list[str]) -> list[str]:
    if not values:
        return [f"{name}: []"]
    return [f"{name}:"] + [f"- {value}" for value in values]


def _metadata(page_type: str, summary: str, raw_relative: str) -> dict[str, object]:
    return {
        "type": page_type,
        "tags": ["llm-wiki"],
        "summary": summary,
        "sources": [raw_relative],
        "updated": date.today().isoformat(),
    }


def _excerpt_as_quote(raw_content: str, max_chars: int = 1000) -> str:
    text = raw_content.strip()
    if not text:
        return "> 这里保留原始资料中的关键片段，后续可由 LLM 精炼。"
    excerpt = text[:max_chars]
    return "\n".join(f"> {line}" if line else ">" for line in excerpt.splitlines())


def _raw_title(raw_file: Path, raw_content: str) -> str:
    for line in raw_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = _clean_markdown_text(stripped.lstrip("#").strip())
            if title:
                return title
    return _title_from_slug(raw_file.stem)


def _extract_concept_terms(
    title: str,
    raw_content: str,
    user_focus: str | None = None,
    limit: int = 5,
) -> list[str]:
    candidates: list[str] = [title]
    if user_focus:
        candidates.append(user_focus)

    for line in raw_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = _clean_markdown_text(stripped.lstrip("#").strip())
            if heading:
                candidates.append(heading)

    for phrase in _concept_phrases(raw_content):
        candidates.append(_title_from_slug(phrase))

    return _dedupe_terms(candidates, limit=limit)


def _extract_entity_terms(
    title: str,
    raw_content: str,
    concept_terms: list[str],
    limit: int = 5,
) -> list[str]:
    candidates: list[str] = []
    for link in extract_wikilinks(raw_content):
        target = link.split("#", 1)[0].split("|", 1)[0].strip().removesuffix(".md")
        if target:
            candidates.append(_title_from_slug(Path(target).name))

    for match in re.finditer(r"\b[A-Z]{2,}(?:[ \t]+[A-Za-z][A-Za-z0-9-]*){0,3}\b", raw_content):
        candidates.append(_trim_entity_descriptor(match.group(0)))

    for match in re.finditer(
        r"\b(?:[A-Z][a-zA-Z0-9]+|[A-Z]{2,})(?:[ \t]+(?:[A-Z][a-zA-Z0-9]+|[A-Z]{2,})){0,3}\b",
        raw_content,
    ):
        candidates.append(_trim_entity_descriptor(match.group(0)))

    concept_slugs = {_slugify(term) for term in concept_terms}
    filtered = [term for term in candidates if _slugify(term) not in concept_slugs]
    terms = _dedupe_terms(filtered, limit=limit)
    if terms:
        return terms
    return _dedupe_terms([title], limit=1)


def _concept_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    suffixes = "|".join(sorted(re.escape(keyword) for keyword in _CONCEPT_KEYWORDS))
    pattern = rf"\b[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[A-Za-z][A-Za-z0-9-]*){{0,3}}[ \t]+(?:{suffixes})\b"
    for match in re.finditer(pattern, text, flags=re.IGNORECASE):
        phrase = match.group(0).strip()
        if phrase:
            phrases.append(phrase)
    return phrases


def _trim_entity_descriptor(term: str) -> str:
    tokens = term.split()
    while len(tokens) > 1 and tokens[-1].lower() in _ENTITY_DESCRIPTOR_WORDS:
        tokens.pop()
    return " ".join(tokens)


def _dedupe_terms(terms: list[str], limit: int) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _clean_markdown_text(term)
        if not normalized:
            continue
        if normalized.lower() in _TERM_STOPWORDS:
            continue
        slug = _slugify(normalized)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        values.append(normalized)
        if len(values) >= limit:
            break
    return values


def _clean_markdown_text(value: str) -> str:
    cleaned = re.sub(r"`([^`]+)`", r"\1", value)
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = cleaned.replace("[[", "").replace("]]", "")
    return re.sub(r"\s+", " ", cleaned).strip(" -:\t")


def _slugify(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", value.lower())
    return "-".join(words)[:80].strip("-")


def _title_from_slug(value: str) -> str:
    cleaned = _clean_markdown_text(value.replace("_", " ").replace("-", " "))
    if not cleaned:
        return value
    if re.fullmatch(r"[A-Za-z0-9 ]+", cleaned):
        return " ".join(token.upper() if token.isupper() else token.capitalize() for token in cleaned.split())
    return cleaned


def _key_point_bullets(raw_content: str, limit: int = 5) -> str:
    sentences = []
    clean_lines = []
    for line in raw_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        clean_lines.append(_clean_markdown_text(stripped.lstrip("-*0123456789. ")))
    text = " ".join(clean_lines)
    for sentence in re.split(r"(?<=[.!?。！？])\s+", text):
        cleaned = sentence.strip()
        if cleaned:
            sentences.append(cleaned)
        if len(sentences) >= limit:
            break
    if not sentences:
        return "- TODO: 根据原始资料补充核心要点。"
    return "\n".join(f"- {sentence}" for sentence in sentences)


def _page_link_bullets(pages: list[PlannedPage], wiki_dir: Path) -> str:
    if not pages:
        return "- 暂无自动识别结果。"
    return "\n".join(f"- [[{_display_link(page.path, wiki_dir)}]]" for page in pages)


def _display_link(path: Path, wiki_dir: Path) -> str:
    return path.resolve().relative_to(wiki_dir.resolve()).as_posix().removesuffix(".md")


_CONCEPT_KEYWORDS = {
    "approach",
    "assessment",
    "check",
    "checks",
    "concept",
    "cases",
    "evaluation",
    "framework",
    "method",
    "process",
    "regression",
    "review",
    "safety",
    "strategy",
    "test",
    "tests",
    "traceability",
    "workflow",
    "workflows",
}

_ENTITY_DESCRIPTOR_WORDS = {
    "approach",
    "assessment",
    "case",
    "cases",
    "check",
    "checks",
    "concept",
    "evaluation",
    "framework",
    "maintenance",
    "method",
    "process",
    "review",
    "set",
    "strategy",
    "task",
    "tasks",
    "test",
    "tests",
    "traceability",
    "workflow",
    "workflows",
}

_TERM_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "or",
    "the",
    "this",
    "that",
}
