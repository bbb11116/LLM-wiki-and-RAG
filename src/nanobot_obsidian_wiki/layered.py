"""Layered Wiki + RAG routing, fusion, and answer caching."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine, RagSearchResult, format_search_results
from nanobot_obsidian_wiki.vault_guard import VaultGuard

RouteName = Literal["wiki_first", "raw_only", "hybrid", "raw_fallback"]


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route: RouteName
    reason: str


@dataclass(frozen=True, slots=True)
class LayeredAnswer:
    question: str
    route: RouteDecision
    output: str
    cache_hit: bool
    wiki_results: list[RagSearchResult]
    raw_results: list[RagSearchResult]


class AnswerCache:
    """Small JSON result cache for high-frequency fixed answers."""

    def __init__(self, config: WikiAgentConfig, guard: VaultGuard):
        self.config = config
        self.guard = guard

    @property
    def path(self) -> Path:
        return self.config.wiki_dir / ".nanobot" / "answer_cache.json"

    def get(self, key: str) -> str | None:
        data = self._load()
        value = data.get(key)
        if not isinstance(value, dict):
            return None
        output = value.get("output")
        return output if isinstance(output, str) else None

    def set(self, key: str, output: str) -> None:
        data = self._load()
        data[key] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "output": output,
        }
        self._store(data)

    def _load(self) -> dict[str, object]:
        try:
            resolved = self.guard.assert_can_read(self._relative_path(self.path))
        except (FileNotFoundError, PermissionError):
            return {}
        try:
            data = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _store(self, data: dict[str, object]) -> None:
        resolved = self.guard.assert_can_write(self._relative_path(self.path))
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _relative_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.config.vault_path).as_posix()


class LayeredKnowledgeEngine:
    """Route questions across the curated Wiki and raw RAG bottom store."""

    def __init__(
        self,
        config: WikiAgentConfig,
        guard: VaultGuard,
        obsidian: ObsidianCLIAdapter,
    ) -> None:
        self.config = config
        self.guard = guard
        self.obsidian = obsidian
        self.rag = LocalRagEngine(config, guard, obsidian)
        self.cache = AnswerCache(config, guard)

    def route(self, question: str) -> RouteDecision:
        normalized = question.lower()
        if _contains(normalized, _REALTIME_HINTS):
            return RouteDecision("raw_only", "Matched realtime/temporary data wording.")
        if _contains(normalized, _COMPLEX_HINTS):
            return RouteDecision("hybrid", "Matched complex synthesis wording.")
        if _contains(normalized, _FIXED_HINTS):
            return RouteDecision("wiki_first", "Matched fixed business/wiki knowledge wording.")
        return RouteDecision("wiki_first", "Default to curated wiki first, then raw fallback.")

    def answer(
        self,
        question: str,
        *,
        top_k: int = 5,
        use_cache: bool = True,
        auto_sync: bool = True,
    ) -> LayeredAnswer:
        if auto_sync:
            self.rag.sync_index(["all"])

        route = self.route(question)
        index = self.rag.load_index()
        index_fingerprint = _files_fingerprint(index.files if index else {})
        cache_key = _cache_key(question, route.route, index_fingerprint)
        if use_cache:
            cached = self.cache.get(cache_key)
            if cached:
                output = cached.replace("- cache: miss", "- cache: hit", 1)
                return LayeredAnswer(question, route, output, True, [], [])

        wiki_results: list[RagSearchResult] = []
        raw_results: list[RagSearchResult] = []

        if route.route in {"wiki_first", "hybrid"}:
            wiki_results = self.rag.search(question, top_k=top_k, scopes=["wiki"], use_cache=True)
        if route.route in {"raw_only", "hybrid"}:
            raw_results = self.rag.search(question, top_k=top_k, scopes=["raw"], use_cache=True)
        if route.route == "wiki_first" and not wiki_results:
            route = RouteDecision("raw_fallback", "No wiki evidence found; downgraded to raw RAG.")
            raw_results = self.rag.search(question, top_k=top_k, scopes=["raw"], use_cache=True)

        output = _format_layered_answer(
            question=question,
            route=route,
            wiki_results=wiki_results,
            raw_results=raw_results,
            cache_state="miss",
        )
        if use_cache and (wiki_results or raw_results):
            self.cache.set(cache_key, output)
        return LayeredAnswer(question, route, output, False, wiki_results, raw_results)


def _format_layered_answer(
    *,
    question: str,
    route: RouteDecision,
    wiki_results: list[RagSearchResult],
    raw_results: list[RagSearchResult],
    cache_state: str,
) -> str:
    if not wiki_results and not raw_results:
        return (
            "# Layered Knowledge Answer\n\n"
            "## Route\n\n"
            f"- route: {route.route}\n"
            f"- reason: {route.reason}\n"
            f"- cache: {cache_state}\n\n"
            "## Answer\n\n"
            "未找到足够依据。Wiki 标准知识与 raw RAG 底库均未召回可引用片段，因此拒绝编造答案。\n\n"
            "## Citations\n\n"
            "- 无\n"
        )

    wiki_summary = _evidence_bullets(wiki_results, "Wiki 标准知识")
    raw_summary = _evidence_bullets(raw_results, "Raw RAG 事实补充")
    citations = _citations(wiki_results + raw_results)
    return (
        "# Layered Knowledge Answer\n\n"
        "## Route\n\n"
        f"- route: {route.route}\n"
        f"- reason: {route.reason}\n"
        f"- cache: {cache_state}\n\n"
        "## Answer\n\n"
        "优先采用 LLM Wiki 中已沉淀的结构化知识；RAG 检索内容只作为事实补充、案例佐证或最新材料。"
        "当 Wiki 与 raw 片段冲突时，应以 Wiki 最新版本为准，并标注差异来源。\n\n"
        f"{wiki_summary}\n\n"
        f"{raw_summary}\n\n"
        "## Wiki Evidence\n\n"
        f"{format_search_results(wiki_results)}\n\n"
        "## Raw RAG Evidence\n\n"
        f"{format_search_results(raw_results)}\n\n"
        "## Citations\n\n"
        f"{citations}\n"
    )


def _evidence_bullets(results: list[RagSearchResult], label: str) -> str:
    if not results:
        return f"- {label}: 未召回可用片段。"
    lines = []
    for result in results[:3]:
        chunk = result.chunk
        lines.append(f"- {label}: {result.snippet} [{chunk.chunk_id}]")
    return "\n".join(lines)


def _citations(results: list[RagSearchResult]) -> str:
    if not results:
        return "- 无"
    seen: set[str] = set()
    lines: list[str] = []
    for result in results:
        chunk = result.chunk
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        lines.append(f"- [{chunk.chunk_id}] {chunk.path}" + (f" > {chunk.heading}" if chunk.heading else ""))
    return "\n".join(lines)


def _contains(text: str, values: set[str]) -> bool:
    return any(value in text for value in values)


def _files_fingerprint(files: dict[str, str]) -> str:
    payload = json.dumps(files, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_key(question: str, route: str, index_fingerprint: str) -> str:
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    payload = f"{route}\n{index_fingerprint}\n{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_REALTIME_HINTS = {
    "latest",
    "new",
    "today",
    "yesterday",
    "temporary",
    "实时",
    "最新",
    "今天",
    "昨天",
    "临时",
    "公告",
    "工单",
    "日报",
    "周报",
}

_COMPLEX_HINTS = {
    "compare",
    "comparison",
    "strategy",
    "plan",
    "tradeoff",
    "综合",
    "比较",
    "方案",
    "策略",
    "权衡",
    "为什么",
    "如何设计",
    "怎么设计",
}

_FIXED_HINTS = {
    "faq",
    "definition",
    "policy",
    "process",
    "standard",
    "是什么",
    "定义",
    "标准",
    "流程",
    "制度",
    "术语",
    "常见问题",
}
