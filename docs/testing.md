# Testing

## 如何运行 pytest

```bash
uv sync
uv run pytest
```

也可以只运行 Obsidian Wiki 相关测试：

```bash
uv run pytest tests/test_obsidian_wiki_api.py tests/tools/test_obsidian_wiki_tool.py tests/test_cli_run.py
uv run pytest tests/test_ingest_workflow.py tests/test_query_workflow.py tests/test_lint_workflow.py
uv run pytest tests/test_rag_workflow.py tests/test_eval_runner.py
uv run pytest tests/test_layered_workflow.py
uv run python -m nanobot_obsidian_wiki --vault tests/fixtures/sample_vault eval --cases eval_cases/obsidian_wiki_smoke.yaml
```

## 测试覆盖模块

- `WikiAgentConfig`
  - vault 路径解析和基础目录校验。
- `SchemaLoader`
  - `TheSchema.md` 加载。
- `VaultGuard`
  - 读取 `raw/` 和 `wiki/`。
  - 禁止写 `raw/`。
  - 禁止路径穿越。
  - 禁止 vault 外路径。
- `ObsidianCLIAdapter`
  - Obsidian CLI 不可用时 fallback。
  - 安全读取、写入、追加、搜索、列文件、链接提取。
- `IntentRouter`
  - 自然语言请求路由到 Ingest / Query / Lint / unknown。
- `IngestWorkflow`
  - dry-run 不写文件。
  - execute 写入 `wiki/sources/`、`wiki/concepts/`、`wiki/entities/`。
  - index 和 log 更新。
- `QueryWorkflow`
  - 只基于 `wiki/` 页面构造候选上下文。
  - 不修改文件。
- `LintWorkflow`
  - frontmatter、summary、wikilink、deadend、orphan 检查。
  - execute 只做低风险修复。
- Obsidian Wiki MCP tool
  - MCP `obsidian_wiki` tool 调用公开 API。
  - AgentLoop 默认不再注册内置 `obsidian_wiki`。
  - 默认 dry-run 不写文件。
- `LocalRagEngine`
  - Markdown/Text chunk 切分、frontmatter metadata 保留。
  - 支持 `wiki` / `raw` / `all` scope 检索。
  - 引用式回答包含 chunk citation。
  - 使用 Chroma 持久化向量库，索引只写入 `wiki/.nanobot/chroma/`。
  - `rag-sync` 支持按文件 hash 增量同步，不必每次重建整库。
- `WikiCompileWorkflow`
  - 筛选稳定 raw 文档，排除临时/实时材料。
  - 复用 IngestWorkflow 编译为 `wiki/sources`、`wiki/concepts`、`wiki/entities`。
  - dry-run 默认不写文件，execute 才写入。
- `LayeredKnowledgeEngine`
  - 智能路由到 `wiki_first` / `raw_only` / `hybrid` / `raw_fallback`。
  - Wiki 标准知识优先，raw RAG 作为事实补充。
  - 答案缓存写入 `wiki/.nanobot/answer_cache.json`。
- Evaluation runner
  - YAML eval cases。
  - workflow、RAG search、RAG answer、layered answer 四类任务。
  - `must_contain`、`must_not_contain`、`must_retrieve`、`must_cite`、`must_not_write` 规则断言。

## 如何使用 sample_vault

测试 fixture 位于：

```text
tests/fixtures/sample_vault/
```

结构包含：

```text
TheSchema.md
raw/sample.md
wiki/index.md
wiki/log.md
wiki/sources/
wiki/entities/
wiki/concepts/
wiki/comparisons/
wiki/overview/
```

测试中需要写入时，会复制 sample vault 到 `tmp_path`，避免污染 fixture。

## dry-run 如何验证不写文件

dry-run 测试会执行 Ingest 或 Router 请求，然后断言目标文件不存在：

```python
assert not (vault / "wiki" / "sources" / "sample.md").exists()
```

这验证了默认行为不会写入 Wiki。

## execute 如何验证写入只发生在 wiki/

execute 测试会在临时 vault 中运行写入工作流，然后检查：

- 新文件只出现在 `wiki/` 下。
- `wiki/log.md` 被追加日志。
- `raw/sample.md` 内容保持不变。
- 写 `raw/` 会抛出 `PermissionError`。

示例：

```python
before = (vault / "raw" / "sample.md").read_text(encoding="utf-8")
workflow.generate_report(execute=True)
assert (vault / "raw" / "sample.md").read_text(encoding="utf-8") == before
```
