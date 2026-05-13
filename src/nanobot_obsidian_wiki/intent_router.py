"""Rule-based intent router for the standalone wiki CLI."""

from __future__ import annotations

import re

from nanobot_obsidian_wiki.models import IntentResult


class IntentRouter:
    """Map user input into a wiki workflow intent without using an LLM."""

    _RAW_PATH_RE = re.compile(r"\b(raw/[^\s\"'，。；;:]+?\.(?:md|txt|pdf))\b", re.IGNORECASE)
    _INGEST_KEYWORDS = (
        "ingest",
        "导入",
        "整理 raw",
        "基于 raw",
        "读取 raw 并生成",
    )
    _LINT_KEYWORDS = (
        "lint",
        "健康检查",
        "检查知识库",
        "审计 wiki",
        "孤立页面",
        "死链",
        "未解析链接",
    )
    _QUERY_KEYWORDS = (
        "是什么",
        "有什么区别",
        "根据 wiki 回答",
        "总结一下",
        "讲了什么",
        "说了什么",
        "讲什么",
        "?",
        "？",
    )

    def route(self, user_input: str) -> IntentResult:
        text = user_input.strip()
        if not text:
            return IntentResult(
                intent="unknown",
                confidence=0.0,
                reason="Input is empty.",
            )

        normalized = text.lower()
        raw_path = self._extract_raw_path(text)

        if self._contains_any(normalized, self._INGEST_KEYWORDS):
            return IntentResult(
                intent="ingest",
                confidence=0.9,
                raw_path=raw_path,
                reason="Matched ingest keyword.",
            )

        if self._contains_any(normalized, self._LINT_KEYWORDS):
            return IntentResult(
                intent="lint",
                confidence=0.9,
                reason="Matched lint keyword.",
            )

        if self._contains_any(normalized, self._QUERY_KEYWORDS):
            return IntentResult(
                intent="query",
                confidence=0.7,
                question=text,
                reason="Matched query-style wording.",
            )

        return IntentResult(
            intent="unknown",
            confidence=0.0,
            raw_path=raw_path,
            question=text if text else None,
            reason="No workflow rule matched.",
        )

    def _extract_raw_path(self, text: str) -> str | None:
        match = self._RAW_PATH_RE.search(text)
        return match.group(1) if match else None

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword.lower() in text for keyword in keywords)
