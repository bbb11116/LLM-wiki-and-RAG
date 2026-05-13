"""Evaluation runner for the Obsidian Wiki Agent and RAG workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from nanobot_obsidian_wiki.api import run_obsidian_wiki_request
from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.layered import LayeredKnowledgeEngine
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.rag import LocalRagEngine, format_search_results
from nanobot_obsidian_wiki.vault_guard import VaultGuard


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    case_id: str
    passed: bool
    task_type: str
    failures: list[str] = field(default_factory=list)
    output: str = ""


@dataclass(frozen=True, slots=True)
class EvalSuiteResult:
    total: int
    passed: int
    failed: int
    results: list[EvalCaseResult]


def run_eval_suite(vault_path: str | Path, cases_path: str | Path | None = None) -> EvalSuiteResult:
    """Run structured eval cases against a vault."""

    vault = Path(vault_path)
    cases = _load_cases(cases_path)
    results = [_run_case(vault, case) for case in cases]
    passed = sum(1 for result in results if result.passed)
    return EvalSuiteResult(
        total=len(results),
        passed=passed,
        failed=len(results) - passed,
        results=results,
    )


def format_eval_report(result: EvalSuiteResult) -> str:
    pass_rate = (result.passed / result.total * 100) if result.total else 0.0
    lines = [
        "# Agent Evaluation Report",
        "",
        "## Summary",
        "",
        f"- total: {result.total}",
        f"- passed: {result.passed}",
        f"- failed: {result.failed}",
        f"- pass_rate: {pass_rate:.1f}%",
        "",
        "## Cases",
        "",
    ]
    for item in result.results:
        status = "PASS" if item.passed else "FAIL"
        lines.extend(
            [
                f"### {item.case_id}",
                "",
                f"- status: {status}",
                f"- type: {item.task_type}",
            ]
        )
        if item.failures:
            lines.append("- failures:")
            lines.extend(f"  - {failure}" for failure in item.failures)
        lines.extend(["", ""])
    return "\n".join(lines).rstrip()


def _run_case(vault: Path, case: dict[str, Any]) -> EvalCaseResult:
    case_id = str(case.get("id") or "unnamed_case")
    task_type = str(case.get("type") or case.get("category") or "workflow")
    expected = case.get("expected") or {}
    output = ""
    retrieved: list[str] = []
    failures: list[str] = []

    try:
        if task_type in {"workflow", "obsidian_workflow"}:
            output = run_obsidian_wiki_request(
                vault,
                str(case.get("input") or case.get("request") or ""),
                execute=bool(case.get("execute", False)),
            )
        elif task_type == "rag_search":
            engine = _engine(vault)
            results = engine.search(
                str(case.get("input") or case.get("question") or ""),
                top_k=int(case.get("top_k", 5)),
                scopes=[str(case.get("scope", "wiki"))],
                use_cache=bool(case.get("use_cache", False)),
            )
            retrieved = [result.chunk.chunk_id for result in results] + [
                result.chunk.path for result in results
            ]
            output = format_search_results(results)
        elif task_type == "rag_answer":
            engine = _engine(vault)
            output = engine.answer(
                str(case.get("input") or case.get("question") or ""),
                top_k=int(case.get("top_k", 5)),
                scopes=[str(case.get("scope", "wiki"))],
                use_cache=bool(case.get("use_cache", False)),
            )
        elif task_type == "layered_answer":
            config, guard, obsidian = _runtime(vault)
            output = LayeredKnowledgeEngine(config, guard, obsidian).answer(
                str(case.get("input") or case.get("question") or ""),
                top_k=int(case.get("top_k", 5)),
                use_cache=bool(case.get("use_cache", True)),
                auto_sync=bool(case.get("auto_sync", True)),
            ).output
        else:
            failures.append(f"Unsupported case type: {task_type}")
    except Exception as exc:
        failures.append(f"Execution error: {exc}")

    failures.extend(_check_expected(vault, expected, output, retrieved))
    return EvalCaseResult(
        case_id=case_id,
        passed=not failures,
        task_type=task_type,
        failures=failures,
        output=output,
    )


def _check_expected(
    vault: Path,
    expected: dict[str, Any],
    output: str,
    retrieved: list[str],
) -> list[str]:
    failures: list[str] = []
    for value in _as_list(expected.get("must_contain")):
        if str(value) not in output:
            failures.append(f"Output missing required text: {value}")
    for value in _as_list(expected.get("must_not_contain")):
        if str(value) in output:
            failures.append(f"Output contains forbidden text: {value}")
    for value in _as_list(expected.get("must_retrieve")):
        target = str(value)
        if not any(target in item for item in retrieved):
            failures.append(f"RAG did not retrieve expected target: {target}")
    if expected.get("must_cite") and not _has_citation(output):
        failures.append("Output does not include a chunk citation.")
    for value in _as_list(expected.get("must_not_write")):
        path = vault / str(value)
        if path.exists():
            failures.append(f"Path should not have been written: {value}")
    return failures


def _load_cases(cases_path: str | Path | None) -> list[dict[str, Any]]:
    if cases_path is None:
        return _default_cases()
    path = Path(cases_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, list):
        cases = data
    else:
        cases = data.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("Eval cases file must contain a list or a top-level 'cases' list.")
    return [case for case in cases if isinstance(case, dict)]


def _default_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "workflow_ingest_dry_run",
            "type": "workflow",
            "input": "请基于 raw/sample.md 进行 Ingest",
            "expected": {
                "must_contain": ["Ingest dry-run plan"],
                "must_not_write": ["wiki/sources/sample.md"],
            },
        },
        {
            "id": "workflow_query_has_candidates",
            "type": "workflow",
            "input": "AI Agent evaluation 讲了什么",
            "expected": {
                "must_contain": ["## 候选依据页面", "## RAG 证据片段"],
            },
        },
        {
            "id": "rag_search_agent_eval",
            "type": "rag_search",
            "input": "agent evaluation tool safety",
            "scope": "all",
            "expected": {
                "must_retrieve": ["raw/sample.md"],
                "must_contain": ["# RAG Search Results"],
            },
        },
        {
            "id": "rag_answer_has_citation",
            "type": "rag_answer",
            "input": "AI Agent evaluation measures what?",
            "scope": "all",
            "expected": {
                "must_cite": True,
                "must_contain": ["## 引用"],
            },
        },
        {
            "id": "layered_answer_routes_and_cites",
            "type": "layered_answer",
            "input": "AI Agent evaluation 是什么？",
            "expected": {
                "must_contain": ["# Layered Knowledge Answer", "## Citations"],
                "must_cite": True,
            },
        },
    ]


def _engine(vault: Path) -> LocalRagEngine:
    config, guard, obsidian = _runtime(vault)
    return LocalRagEngine(config, guard, obsidian)


def _runtime(vault: Path) -> tuple[WikiAgentConfig, VaultGuard, ObsidianCLIAdapter]:
    config = WikiAgentConfig.from_vault(vault)
    guard = VaultGuard(config)
    obsidian = ObsidianCLIAdapter(config, guard)
    return config, guard, obsidian


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _has_citation(output: str) -> bool:
    return "#chunk-" in output and ("[wiki/" in output or "[raw/" in output)
