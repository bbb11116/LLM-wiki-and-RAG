"""Rule-based query workflow over existing wiki Markdown pages."""

from __future__ import annotations

import re

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.models import WikiSchema
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine, format_search_results
from nanobot_obsidian_wiki.utils.frontmatter import extract_wikilinks
from nanobot_obsidian_wiki.vault_guard import VaultGuard


class QueryWorkflow:
    """Find and summarize candidate wiki pages without RAG or embeddings."""

    def __init__(
        self,
        config: WikiAgentConfig,
        schema: WikiSchema,
        guard: VaultGuard,
        obsidian: ObsidianCLIAdapter,
        llm_client: object | None = None,
        rag_scopes: list[str] | None = None,
    ):
        self.config = config
        self.schema = schema
        self.guard = guard
        self.obsidian = obsidian
        self.llm_client = llm_client
        self.rag_scopes = rag_scopes or ["wiki"]
        self.rag = LocalRagEngine(config, guard, obsidian)

    def find_candidate_pages(self, question: str, limit: int = 5) -> list[str]:
        keywords = _extract_keywords(question)
        candidates: list[str] = []

        index_text = ""
        try:
            index_text = self.obsidian.read_note("wiki/index.md")
        except (FileNotFoundError, PermissionError):
            index_text = ""

        index_pages = _index_pages(index_text)
        for page in index_pages:
            if self._page_exists(page) and _matches_question(page, index_text, keywords):
                _append_unique(candidates, page)

        for keyword in keywords:
            for page in self.obsidian.search(keyword, folder="wiki"):
                _append_unique(candidates, page)

        return candidates[:limit]

    def _page_exists(self, page: str) -> bool:
        try:
            self.obsidian.read_note(page)
            return True
        except (FileNotFoundError, PermissionError):
            return False

    def build_context(self, candidate_pages: list[str], max_chars: int = 8000) -> str:
        if not candidate_pages:
            return ""

        chunks: list[str] = []
        total = 0
        for page in candidate_pages:
            try:
                content = self.obsidian.read_note(page).strip()
            except (FileNotFoundError, PermissionError):
                continue
            block = f"[PAGE] {page}\n{content}\n"
            remaining = max_chars - total
            if remaining <= 0:
                break
            if len(block) > remaining:
                block = block[:remaining].rstrip() + "\n"
            chunks.append(block)
            total += len(block)
        return "\n".join(chunks).strip()

    def answer(self, question: str) -> str:
        candidates = self.find_candidate_pages(question)
        context = self.build_context(candidates)
        rag_results = self.rag.search(question, top_k=5, scopes=self.rag_scopes)
        rag_context = format_search_results(rag_results)

        if (not candidates or not context) and not rag_results:
            return (
                "## 回答\n\n"
                "未找到足够依据。当前版本只会读取 wiki/index.md 并在 wiki/ 中做简单关键词匹配，"
                "同时使用本地 RAG 对允许范围内的 Markdown chunk 做检索；当前没有匹配到可引用证据，"
                "也不会自动写回。\n\n"
                "## 候选依据页面\n\n"
                "- 无\n\n"
                "## RAG 证据片段\n\n"
                "无\n\n"
                "## 页面摘录\n\n"
                "无\n\n"
                "## 可写回建议\n\n"
                "- 如果该问题形成稳定结论，建议写入 wiki/overview/xxx.md 或 wiki/comparisons/xxx.md。\n"
                "- 默认不自动写回。"
            )

        bullets = "\n".join(f"- [[{_display_link(page)}]]" for page in candidates) or "- 无"
        context_block = context or "无"
        return (
            "## 回答\n\n"
            "当前版本已定位到以下相关 Wiki 页面，并通过本地 RAG 检索出可引用证据片段。"
            "请基于这些证据进一步综合回答，或交给上层 LLM 生成自然语言答案。\n\n"
            "## 候选依据页面\n\n"
            f"{bullets}\n\n"
            "## RAG 证据片段\n\n"
            f"{rag_context}\n\n"
            "## 页面摘录\n\n"
            f"{context_block}\n\n"
            "## 可写回建议\n\n"
            "- 如果该问题形成稳定结论，建议写入 wiki/overview/xxx.md 或 wiki/comparisons/xxx.md。\n"
            "- 默认不自动写回。"
        )


def _extract_keywords(question: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", question)
    keywords: list[str] = []
    for token in tokens:
        clean = token.strip()
        if not clean:
            continue
        if re.fullmatch(r"[A-Za-z0-9_-]+", clean) and len(clean) < 3:
            continue
        if len(clean) < 2:
            continue
        _append_unique(keywords, clean)
    return keywords


def _index_pages(index_text: str) -> list[str]:
    pages = ["wiki/index.md"]
    for link in extract_wikilinks(index_text):
        page = _link_to_wiki_path(link)
        if page:
            _append_unique(pages, page)
    return pages


def _link_to_wiki_path(link: str) -> str | None:
    target = link.strip().removesuffix(".md")
    if not target:
        return None
    if target.startswith("wiki/"):
        return f"{target}.md"
    return f"wiki/{target}.md"


def _matches_question(page: str, index_text: str, keywords: list[str]) -> bool:
    haystack = f"{page}\n{index_text}".lower()
    return any(keyword.lower() in haystack for keyword in keywords)


def _append_unique(values: list[str], value: str) -> None:
    normalized = value.replace("\\", "/")
    if normalized not in values:
        values.append(normalized)


def _display_link(page: str) -> str:
    return page.removeprefix("wiki/").removesuffix(".md")
