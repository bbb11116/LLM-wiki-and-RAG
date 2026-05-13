**nanobot** 是一个开源、轻量级的个人 AI Agent 框架，设计风格接近 [OpenClaw](https://github.com/openclaw/openclaw)、[Claude Code](https://www.anthropic.com/claude-code) 和 [Codex](https://www.openai.com/codex/)。它把核心 Agent loop 保持在小而可读的范围内，同时支持聊天渠道、记忆、MCP、工具调用和生产部署，让你可以用较低成本搭建一个长期运行的个人 Agent。

本仓库还包含一个基于 Nanobot 二次开发的 **Schema-driven Obsidian LLM Wiki Agent**：通过 `TheSchema.md`、Obsidian CLI、`VaultGuard`、Chroma RAG 和分层路由，为本地 Obsidian Markdown 知识库提供 Ingest、Query、Lint、Wiki 编译、向量检索、分层问答与自动评测能力。


## 核心特性

- **轻量可读**：核心 Agent loop 保持简洁，便于学习、调试和二次开发。
- **适合研究和改造**：代码结构清楚，适合作为 Agent 框架实验、课程项目或个人工具底座。
- **实用能力内置**：支持聊天渠道、OpenAI-compatible API、记忆、MCP、文件工具和部署路径。
- **易扩展**：可以新增 tool、skill、channel 或独立 sidecar，而不必重写核心 loop。
- **本地知识库治理与 RAG**：新增 `nanobot_obsidian_wiki` 模块，可维护 Obsidian LLM Wiki vault，并支持 Chroma 向量检索、Wiki/raw 双库融合、增量同步和评测报告。

## 安装

> [!IMPORTANT]
> 如果你想体验最新功能或进行二次开发，推荐从源码安装。

**从源码安装**

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

## Schema-driven Obsidian LLM Wiki Agent

本仓库新增了实验性的 `nanobot_obsidian_wiki` sidecar，用于维护符合 `raw/`、`wiki/`、`TheSchema.md` 范式的 Obsidian LLM Wiki vault。

核心思路是分层：**LLM Wiki 做知识沉淀和结构化大脑，RAG 做实时原始素材与兜底检索**。稳定、高价值、长期复用的知识会被编译进 `wiki/`；临时公告、工单、聊天记录、实时材料保留在 `raw/` 和 Chroma RAG 底库中。用户提问时，系统会根据问题自动选择 Wiki、raw RAG 或双路融合。

- `raw/` 是原始资料层，只读。
- `wiki/` 是结构化知识层，可写。
- `TheSchema.md` 是规则层，Agent 启动后必须读取。
- 默认 dry-run，只有显式 `--execute` 或 `execute=true` 才允许写入。
- 所有写操作必须经过 `VaultGuard`，并追加到 `wiki/log.md`。
- Chroma 索引和答案缓存只写入 `wiki/.nanobot/`，不会修改 `raw/`。

完整文档：

- [Schema-driven Obsidian LLM Wiki Agent](./docs/obsidian_wiki_agent.md)
- [Architecture](./docs/architecture.md)
- [Testing](./docs/testing.md)
- [Resume Description](./docs/resume_description.md)

### 环境与测试

本项目使用 `uv` 管理开发环境：

```bash
uv sync
uv run pytest
uv run python -m nanobot_obsidian_wiki --help
```

如果你使用源码仓库中的 `.venv`，也可以直接运行：

```bash
.venv/bin/python -m nanobot_obsidian_wiki --help
```

### Vault 结构

```text
TheSchema.md
raw/
wiki/
  index.md
  log.md
  sources/
  entities/
  concepts/
  comparisons/
  overview/
```

### 在 Nanobot 对话中使用知识库

推荐的日常用法不是手动跑 CLI，而是把 Obsidian Wiki/RAG sidecar 作为 MCP 工具接入 Nanobot。接入后，你可以直接在 Nanobot 对话里说“同步知识库”“把稳定资料编译进 Wiki”“基于知识库回答这个问题”。

#### 1. 准备 Vault 路径

先准备一个 Obsidian vault，结构如下：

```text
your-vault/
  TheSchema.md
  raw/
  wiki/
    index.md
    log.md
    sources/
    entities/
    concepts/
    comparisons/
    overview/
```

`raw/` 放原始资料，`wiki/` 放沉淀后的结构化知识。`raw/` 是只读层，Agent 不会写入；所有写操作都限制在 `wiki/`。

如果不想每次在对话中提供路径，可以设置环境变量：

```bash
export NANOBOT_OBSIDIAN_VAULT_PATH="/absolute/path/to/your-vault"
```

#### 2. 配置 Nanobot MCP

在 `~/.nanobot/config.json` 中添加 MCP server。推荐把 vault 路径放到 `env` 中，这样对话时不用反复传 `vault_path`：

```json
{
  "tools": {
    "mcpServers": {
      "obsidian": {
        "command": "uv",
        "args": ["run", "nanobot-obsidian-wiki-mcp"],
        "env": {
          "NANOBOT_OBSIDIAN_VAULT_PATH": "/absolute/path/to/your-vault"
        },
        "enabledTools": [
          "obsidian_wiki",
          "obsidian_rag_sync",
          "obsidian_rag_search",
          "obsidian_rag_answer",
          "obsidian_layered_answer",
          "obsidian_wiki_compile",
          "obsidian_eval"
        ]
      }
    }
  }
}
```

如果你不是通过 `uv` 运行，也可以把 `command` 换成已安装的可执行文件：

```json
{
  "command": "nanobot-obsidian-wiki-mcp",
  "args": []
}
```

然后启动 Nanobot：

```bash
nanobot agent
```

#### 3. 第一次对话建议

你可以先让 Nanobot 介绍知识库能力和当前配置：

```text
请介绍一下你现在接入的 Obsidian LLM Wiki 知识库能力，包括 raw、wiki、RAG、分层问答和安全写入边界。
```

检查 vault 是否可用：

```text
请检查当前 Obsidian Wiki vault 是否可用。
```

同步 RAG 底库：

```text
请同步 Obsidian RAG 索引，范围包括 raw 和 wiki。
```

把稳定资料编译进 Wiki：

```text
请先 dry-run 编译稳定 raw 文档到 LLM Wiki，告诉我会写哪些文件，不要实际写入。
```

确认后执行：

```text
确认执行，把稳定 raw 文档编译进 LLM Wiki。
```

#### 4. 在对话中提问

推荐问答入口是分层回答，也就是让 Agent 自动判断该查 Wiki、raw RAG，还是双路融合：

```text
请使用分层知识库回答：AI Agent evaluation 讲了什么？
```

固定业务、FAQ、术语、制度、流程类问题：

```text
根据 LLM Wiki 回答：我们的 Agent 评测流程是什么？
```

最新公告、临时材料、工单、日报类问题：

```text
请从 raw RAG 底库里查一下今天最新公告提到了什么。
```

复杂综合问题：

```text
请综合 LLM Wiki 标准知识和 raw RAG 原始片段，比较 Agent 基础功能评测和 RAG 评测的差异，并给出引用。
```

只检索证据，不生成最终答案：

```text
请检索和“工具调用安全评测”相关的 raw/wiki 证据片段，列出 chunk 引用。
```

#### 5. 对话中的写入安全

默认情况下，写入类请求会 dry-run：

```text
请基于 raw/sample.md 进行 Ingest，先只给 dry-run 计划。
```

只有你明确确认，才执行写入：

```text
确认执行 ingest raw/sample.md。
```

写入只允许发生在 `wiki/`，不会修改 `raw/`。所有写入会追加到 `wiki/log.md`。

#### 6. 对话中的评测

你可以让 Nanobot 跑评测集：

```text
请运行 Obsidian Wiki smoke eval，检查 workflow、RAG 和 layered answer 是否通过。
```

也可以要求它解释失败项：

```text
如果评测失败，请按严重程度列出失败 case、原因和建议修复方案。
```

### 常用 MCP 工具

在 Nanobot 中，MCP 工具名通常会带 server 前缀，例如 `obsidian_layered_answer` 会注册为 `mcp_obsidian_obsidian_layered_answer`。

| MCP tool | 用途 | 对话里可以怎么说 |
|----------|------|------------------|
| `mcp_obsidian_obsidian_wiki` | 自然语言 Ingest / Query / Lint | “请检查 Wiki 健康度” |
| `mcp_obsidian_obsidian_wiki_compile` | 批量编译稳定 raw 到 Wiki | “把稳定 raw 文档编译进 Wiki，先 dry-run” |
| `mcp_obsidian_obsidian_rag_sync` | 增量同步 Chroma RAG 索引 | “同步 RAG 索引，scope=all” |
| `mcp_obsidian_obsidian_rag_search` | 检索 raw/wiki 证据片段 | “只检索证据片段，不生成答案” |
| `mcp_obsidian_obsidian_rag_answer` | 生成带引用的 RAG 回答 | “用 RAG 回答并给引用” |
| `mcp_obsidian_obsidian_layered_answer` | 分层路由与融合回答，推荐问答入口 | “使用分层知识库回答这个问题” |
| `mcp_obsidian_obsidian_eval` | 运行 workflow/RAG/layered answer 评测 | “运行 Obsidian Wiki smoke eval” |

### 独立 CLI 使用

CLI 适合调试、批处理和 CI。Nanobot 对话里会通过 MCP 调用同一套能力。

检查 vault：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" check
```

#### 1. 编译稳定知识到 LLM Wiki

先 dry-run 看计划，不写入：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" wiki-compile
```

确认后执行写入：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" wiki-compile --execute
```

`wiki-compile` 会筛选稳定 raw 文档，跳过临时、实时、公告、工单、日报等动态材料，并复用 Ingest 工作流写入 `wiki/sources/`、`wiki/concepts/`、`wiki/entities/`。

#### 2. 手动 Ingest 单个 raw 文件

Ingest dry-run：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" ingest "raw/sample.md" --dry-run
```

Ingest 执行写入：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" ingest "raw/sample.md" --execute
```

执行模式会根据 `TheSchema.md` 写入来源摘要页、自动提取的概念页与实体页，并更新
`wiki/index.md`、追加 `wiki/log.md`。

#### 3. 查询 Wiki，并自动附带 RAG 证据

Query 会先查 `wiki/index.md`、wikilink 和关键词搜索，再自动执行 Chroma RAG 检索。默认只检索 `wiki/`，适合查询已沉淀的结构化知识。

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" query "AI Agent evaluation 讲了什么"
```

#### 4. 构建和同步 Chroma RAG 索引

首次建立持久化索引：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" rag-index --scope all --persist
```

日常增量同步：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" rag-sync --scope all
```

检查索引健康度：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" rag-health --scope all
```

`rag-sync` 会根据文件 hash 判断新增、修改、删除，只更新受影响 chunk，不必每次重建整个向量库。

#### 5. 直接使用 RAG 检索或回答

检索证据片段：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" rag-search --scope all "某个问题"
```

生成带引用的 RAG 回答：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" rag-answer --scope all "某个问题"
```

`scope` 可选：

| scope | 含义 |
|------|------|
| `wiki` | 只检索结构化 Wiki，适合稳定知识 |
| `raw` | 只检索原始资料，适合实时、临时、长尾问题 |
| `all` | 同时检索 Wiki 与 raw |

#### 6. 分层问答：推荐入口

如果你想让系统自动决定查 Wiki、查 raw，还是双路融合，使用：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" layered-answer "某个问题"
```

分层路由规则：

| 路由 | 触发场景 | 行为 |
|------|----------|------|
| `wiki_first` | 固定业务、FAQ、术语、制度、流程 | 优先查 LLM Wiki，不够再降级 |
| `raw_only` | 最新公告、临时材料、工单、日报、实时数据 | 直接查 raw RAG 底库 |
| `hybrid` | 复杂综合、方案、比较、策略问题 | Wiki 标准答案 + raw 事实补充 |
| `raw_fallback` | Wiki 无相关知识 | 自动降级到 raw RAG |

分层回答会输出：

- 路由决策和原因。
- Wiki Evidence。
- Raw RAG Evidence。
- chunk 级引用。
- 答案缓存命中状态。

高频问题的答案会缓存到：

```text
wiki/.nanobot/answer_cache.json
```

#### 7. Lint 与评测

Lint：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" lint
```

运行内置评测：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" eval
```

运行示例评测集：

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" eval --cases eval_cases/obsidian_wiki_smoke.yaml
```

评测覆盖 workflow、RAG search、RAG answer、layered answer，支持 `must_contain`、`must_not_contain`、`must_retrieve`、`must_cite`、`must_not_write` 等规则断言。

#### 8. 自然语言路由

```bash
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" run "请基于 raw/sample.md 进行 Ingest"
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" run "请对 wiki 做一次 Lint"
uv run python -m nanobot_obsidian_wiki --vault "path/to/vault" run "根据 wiki 回答 AI Agent evaluation 讲了什么"
```

### 推荐使用流程

```text
1. 把原始资料放入 raw/
2. rag-sync --scope all，建立 raw RAG 底库
3. wiki-compile，筛选稳定资料并生成结构化 Wiki
4. rag-sync --scope all，同步 Wiki 与 raw 双库
5. layered-answer，由路由器自动选择 Wiki / raw / hybrid
6. eval --cases ...，验证召回、引用、安全写入和回答质量
```
