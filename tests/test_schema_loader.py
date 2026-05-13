from pathlib import Path

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.schema_loader import SchemaLoader


def test_schema_loader_reads_sample_schema():
    vault = Path("tests/fixtures/sample_vault")
    schema = SchemaLoader(WikiAgentConfig.from_vault(vault)).load()

    assert "raw/ is read-only" in schema.schema_text
    assert "all writes must be logged" in schema.schema_text
    assert schema.page_type_dirs["source"] == "wiki/sources"
    assert schema.workflows == ["ingest", "query", "lint"]
