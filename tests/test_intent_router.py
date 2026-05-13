from nanobot_obsidian_wiki.intent_router import IntentRouter


def test_intent_router_detects_ingest_and_raw_path():
    result = IntentRouter().route("请基于 raw/sample.md 进行 Ingest")

    assert result.intent == "ingest"
    assert result.confidence == 0.9
    assert result.raw_path == "raw/sample.md"


def test_intent_router_detects_lint_keyword():
    result = IntentRouter().route("请对 wiki 做一次 Lint")

    assert result.intent == "lint"
    assert result.confidence == 0.9


def test_intent_router_detects_orphan_page_lint():
    result = IntentRouter().route("检查知识库有没有孤立页面")

    assert result.intent == "lint"
    assert result.confidence == 0.9


def test_intent_router_detects_query_question():
    result = IntentRouter().route("LLM-as-a-Judge 和人工评测有什么区别？")

    assert result.intent == "query"
    assert result.confidence == 0.7
    assert result.question == "LLM-as-a-Judge 和人工评测有什么区别？"


def test_intent_router_empty_string_unknown():
    result = IntentRouter().route("")

    assert result.intent == "unknown"
    assert result.confidence == 0.0
