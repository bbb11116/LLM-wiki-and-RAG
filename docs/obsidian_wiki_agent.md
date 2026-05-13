# Schema-driven Obsidian LLM Wiki Agent

## 项目简介

本项目基于 Nanobot 二次开发，结合 Obsidian CLI 和 LLM Wiki 的
`TheSchema.md`，构建一个本地个人知识库维护 Agent。它面向 Obsidian vault
中的 `raw/`、`wiki/` 和 `TheSchema.md` 结构，提供 Ingest、Query、Lint 三类
工作流，让 Agent 能按规则维护本地 Markdown Wiki。

## 和 llm-wiki-obsidian-blink 的关系

- `llm-wiki-obsidian-blink` 提供 `raw/`、`wiki/`、`TheSchema.md` 的知识库范式。
- 本项目让 Nanobot 自动读取 `TheSchema.md` 并执行 Ingest / Query / Lint。
- 从“人工提示 AI 操作 Wiki”升级为“Agent 自动执行 Wiki 工作流”。

## 和 Nanobot 的关系

- Nanobot 提供 Agent 框架与工具调用入口。
- `nanobot_obsidian_wiki` 是新增的知识库工具模块。
- 当前采用最小侵入方式接入：保留独立 CLI，同时提供 `obsidian_wiki` MCP tool。
- 不大改核心 agent loop，不改变 Nanobot 的 provider、session、channel、MCP 运行机制。

## 环境配置

本项目使用 `uv` 管理环境：

```bash
uv sync
uv run pytest
uv run python -m nanobot_obsidian_wiki --help
```

## Vault 结构要求

```text
raw/
wiki/
  sources/
  entities/
  concepts/
  comparisons/
  overview/
  index.md
  log.md
TheSchema.md
```

## 使用示例

Check:

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" check
```

Ingest dry-run:

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" ingest "raw/sample.md" --dry-run
```

Ingest execute:

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" ingest "raw/sample.md" --execute
```

Query:

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" query "AI Agent evaluation 讲了什么"
```

Lint:

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" lint
```

Router:

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" run "请对 wiki 做一次 Lint"
```

Nanobot tool 可以通过工具参数传入 `vault_path`，也可以使用环境变量：

```bash
NANOBOT_OBSIDIAN_VAULT_PATH=path/to/vault
```

MCP 接入配置示例：

```json
{
  "tools": {
    "mcpServers": {
      "obsidian": {
        "command": "uv",
        "args": ["run", "nanobot-obsidian-wiki-mcp"],
        "enabledTools": ["obsidian_wiki"]
      }
    }
  }
}
```

在 Nanobot 内部，该 MCP tool 会以 `mcp_obsidian_obsidian_wiki` 的名字注册。

示例用户输入：

- 请基于 raw/sample.md 进行 Ingest
- 请对 wiki 做一次 Lint
- 根据 wiki 回答 AI Agent evaluation 讲了什么

## 安全策略

- `raw/` 只读。
- `wiki/` 可写。
- 默认 dry-run。
- 只有 `--execute` 或 tool 参数 `execute=true` 才写入。
- 所有写入追加 `wiki/log.md`。
- 禁止删除文件。
- 禁止写 vault 外路径。
- 禁止路径穿越，例如 `../outside.md`。
- Nanobot 不直接操作 vault 文件，必须经过 `IntentRouter -> Workflow -> ObsidianCLIAdapter -> VaultGuard`。

## 当前支持

- `TheSchema.md` 加载。
- Ingest：读取 `raw/`，写入 `wiki/sources/`、`wiki/concepts/`、`wiki/entities/`，
  并更新 `wiki/index.md` 与 `wiki/log.md`。
- Query。
- Lint。
- Obsidian CLI Adapter。
- fallback 文件读写。
- frontmatter 检查。
- wikilink 检查。
- dry-run / execute。
- MCP `obsidian_wiki` tool。
- Chroma-backed RAG：`rag-index`、`rag-search`、`rag-answer`、`rag-health`。
- 增量 RAG 同步：`rag-sync`。
- 分层回答：`layered-answer`，支持 Wiki 优先、raw fallback、hybrid 融合与答案缓存。
- Wiki 编译：`wiki-compile`，筛选稳定 raw 文档并批量沉淀为结构化 Wiki。
- MCP `obsidian_rag_index` / `obsidian_rag_search` / `obsidian_rag_answer` tools。
- MCP `obsidian_rag_sync` / `obsidian_layered_answer` / `obsidian_wiki_compile` tools。
- MCP `obsidian_eval` tool。

## 当前不支持

- 外部 neural embedding provider 自动配置。
- 真正 LLM 批量改写和人工审批 UI。
- PDF OCR。
- 自动删除 / 合并笔记。
- 大规模自动重写。
- 复杂知识图谱推理。

## 后续计划

- 更完整地接入 Nanobot 主 Agent tool registry 配置项。
- 支持 PDF 转 Markdown。
- 支持更强的 concept/entity 自动抽取。
- 支持自动生成 MOC / overview 页面。
- 支持更精细的 LLM prompt。
- 支持用户确认后批量修复。
