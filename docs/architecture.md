# Architecture

## 系统架构图

```mermaid
flowchart TD
    User["User / Nanobot"] --> CLI["CLI or MCP obsidian_wiki Tool"]
    CLI --> API["run_obsidian_wiki_request"]
    API --> Router["IntentRouter"]
    Router --> Ingest["IngestWorkflow"]
    Router --> Query["QueryWorkflow"]
    Router --> Lint["LintWorkflow"]
    Ingest --> Adapter["ObsidianCLIAdapter"]
    Query --> Adapter
    Lint --> Adapter
    Adapter --> Guard["VaultGuard"]
    Guard --> Vault["Obsidian Vault"]
    Vault --> Raw["raw/"]
    Vault --> Wiki["wiki/"]
    Wiki --> Index["wiki/index.md"]
    Wiki --> Log["wiki/log.md"]
    Vault --> Schema["TheSchema.md"]
```

## 模块说明

- `nanobot_obsidian_wiki.config`
  - 定义 `WikiAgentConfig`，解析并校验 vault、schema、raw、wiki、log 路径。
- `nanobot_obsidian_wiki.schema_loader`
  - 启动工作流前读取 `TheSchema.md`，返回 `WikiSchema`。
- `nanobot_obsidian_wiki.intent_router`
  - 将自然语言请求路由为 `ingest`、`query`、`lint` 或 `unknown`。
- `nanobot_obsidian_wiki.obsidian_cli`
  - 封装 Obsidian CLI，CLI 不可用时 fallback 到 Python 文件读写。
- `nanobot_obsidian_wiki.vault_guard`
  - 负责路径安全和权限边界，防止 vault 外访问、路径穿越和 `raw/` 写入。
- `nanobot_obsidian_wiki.workflows`
  - 实现 Ingest、Query、Lint 工作流。
- `nanobot_obsidian_wiki.mcp_server`
  - 提供 MCP stdio server，暴露 `obsidian_wiki` tool，调用公开 Python API。

## 数据流

```mermaid
sequenceDiagram
    participant U as User
    participant T as CLI / MCP Tool
    participant R as IntentRouter
    participant W as Workflow
    participant A as ObsidianCLIAdapter
    participant G as VaultGuard
    participant V as Vault

    U->>T: Natural-language request
    T->>R: route(request)
    R-->>T: IntentResult
    T->>W: execute selected workflow
    W->>A: read/search/write request
    A->>G: assert_can_read / assert_can_write
    G->>V: resolved safe path
    A->>V: Obsidian CLI or Python fallback
    V-->>A: Markdown content / write result
    A-->>W: result
    W-->>T: Markdown report
    T-->>U: Response
```

## Ingest 流程

```mermaid
flowchart TD
    A["raw/sample.md"] --> B["VaultGuard.assert_can_read"]
    B --> C["IngestWorkflow.build_plan"]
    C --> D{"execute?"}
    D -- "no" --> E["Return dry-run WritePlan"]
    D -- "yes" --> F["Render source, concept, entity pages"]
    F --> G["Write wiki/sources, wiki/concepts, wiki/entities"]
    G --> H["Append wiki/index.md links"]
    H --> I["Append wiki/log.md"]
```

## Query 流程

```mermaid
flowchart TD
    A["Question"] --> B["Extract keywords"]
    B --> C["Read wiki/index.md"]
    C --> D["Obsidian search in wiki/"]
    D --> E["Merge candidate pages"]
    E --> F["Read Markdown pages"]
    F --> G["Build context"]
    G --> H["Return structured answer context"]
```

## Lint 流程

```mermaid
flowchart TD
    A["Scan wiki/*.md"] --> B["Check frontmatter"]
    A --> C["Check wikilinks"]
    A --> D["Check deadend pages"]
    A --> E["Check orphan pages"]
    B --> F["Generate report"]
    C --> F
    D --> F
    E --> F
    F --> G{"execute?"}
    G -- "no" --> H["Report only"]
    G -- "yes" --> I["Low-risk frontmatter/summary fixes"]
    I --> J["Append wiki/log.md"]
```

## 安全写入流程

```mermaid
flowchart TD
    A["Workflow wants to write"] --> B["ObsidianCLIAdapter"]
    B --> C["VaultGuard.assert_can_write"]
    C --> D{"Inside vault?"}
    D -- "no" --> X["Reject"]
    D -- "yes" --> E{"Under raw/?"}
    E -- "yes" --> X
    E -- "no" --> F{"Under wiki/?"}
    F -- "no" --> X
    F -- "yes" --> G{"execute enabled?"}
    G -- "no" --> H["Return dry-run plan"]
    G -- "yes" --> I["Write wiki/"]
    I --> J["Append wiki/log.md"]
```
