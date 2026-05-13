from nanobot_obsidian_wiki.utils.frontmatter import (
    dump_frontmatter,
    ensure_required_fields,
    extract_wikilinks,
    parse_frontmatter,
)


def test_parse_frontmatter_metadata_and_body():
    metadata, body = parse_frontmatter("---\ntitle: Test\ntags:\n  - ai\n---\n# Body\n")

    assert metadata["title"] == "Test"
    assert metadata["tags"] == ["ai"]
    assert body == "# Body\n"


def test_parse_frontmatter_absent():
    metadata, body = parse_frontmatter("# Body\n")

    assert metadata == {}
    assert body == "# Body\n"


def test_dump_frontmatter_round_trips_through_parse():
    markdown = dump_frontmatter({"title": "Test", "tags": ["ai"]}, "# Body\n")

    metadata, body = parse_frontmatter(markdown)

    assert metadata == {"title": "Test", "tags": ["ai"]}
    assert body == "# Body\n"


def test_ensure_required_fields_preserves_existing_summary():
    metadata = ensure_required_fields({"summary": "Existing summary"}, "concept")

    assert metadata["type"] == "concept"
    assert metadata["summary"] == "Existing summary"
    assert metadata["tags"] == []
    assert metadata["sources"] == []
    assert metadata["updated"]


def test_extract_wikilinks_simple_target():
    links = extract_wikilinks("See [[AI Agent]] for details.")

    assert links == ["AI Agent"]


def test_extract_wikilinks_alias_returns_target_only():
    links = extract_wikilinks("See [[LLM-as-a-Judge|评测方法]].")

    assert links == ["LLM-as-a-Judge"]


def test_extract_wikilinks_embeds_are_included_in_first_version():
    links = extract_wikilinks("Diagram: ![[agent-flow.png]]")

    assert links == ["agent-flow.png"]
