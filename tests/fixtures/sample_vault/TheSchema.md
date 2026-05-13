# TheSchema

This simplified schema defines the first-stage Obsidian LLM Wiki rules.

- raw/ is read-only
- wiki/ is writable
- Ingest reads raw and writes wiki/sources, wiki/concepts, wiki/entities
- Query reads wiki/index.md and related wiki pages
- Lint checks frontmatter, links, orphan pages, unresolved links
- all writes must be logged to wiki/log.md

