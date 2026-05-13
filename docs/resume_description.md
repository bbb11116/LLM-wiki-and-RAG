# Resume Description

## 简历项目名称

Personal LLM Wiki Agent：个人知识库智能维护与 RAG 评测系统

## 简历 Bullet

### 简洁版

- 基于 Nanobot 与 llm-wiki 知识库范式构建 Schema-driven Obsidian Agent，设计 `TheSchema.md` 运行时规则约束 `raw/` 只读、`wiki/` 可写，封装 Obsidian CLI 适配层，并实现 Ingest / Query / Lint 工作流，支持来源摘要生成、frontmatter/标签/双向链接维护、死链与孤立笔记检测，以及 Plan-Confirm-Execute-Log 安全写入机制。
- 在 Query Workflow 基础上扩展 Chroma-backed RAG 与分层问答架构，引入 Markdown chunk 切分、metadata 抽取、持久化向量索引、增量同步、双库检索与答案缓存，实现基于证据片段的知识库问答。
- 设计引用式回答与评测体系，要求回答绑定具体 raw/wiki chunk，并通过结构化 eval case、规则断言和报告生成评测 Agent 基础功能、知识库 Workflow、RAG 召回与答案忠实性。

### 技术版

- 在 Nanobot 中最小侵入式新增 `nanobot_obsidian_wiki` 模块和 `obsidian_wiki` MCP tool，通过 `IntentRouter -> Workflow -> ObsidianCLIAdapter -> VaultGuard` 调用链实现安全知识库维护。
- 实现 TheSchema.md 加载、Obsidian CLI adapter、CLI fallback 文件读写、frontmatter/wikilink 解析，以及 Ingest / Query / Lint 三类工作流。
- 构建 VaultGuard 路径安全层，防止 vault 外访问、路径穿越和 `raw/` 写入；所有写操作默认 dry-run，只有 `--execute` 或 `execute=true` 才允许写入 `wiki/` 并追加 `wiki/log.md`。
- 新增 `LocalRagEngine`，对 `raw/` 与 `wiki/` 中的 Markdown/Text 文件进行结构化 chunk、frontmatter metadata 提取、wikilink 保留，并使用 Chroma 持久化向量库进行检索；索引缓存只写入 `wiki/.nanobot/chroma/`，继续复用 VaultGuard 安全边界。
- 实现 `rag-sync` 增量同步策略，基于文件 hash 识别新增、修改和删除文档，只更新受影响 chunk，避免全量重建向量库。
- 实现 `LayeredKnowledgeEngine` 智能路由层，将问题分流为 `wiki_first`、`raw_only`、`hybrid`、`raw_fallback`，优先采用 LLM Wiki 标准知识，raw RAG 仅作为事实补充、案例佐证或最新材料。
- 实现 `WikiCompileWorkflow`，筛选稳定 raw 文档并批量编译为结构化 Wiki 页面，动态/临时资料仅进入 raw RAG 底库，降低 Wiki 维护成本和内容冗余。
- 暴露 `rag-index`、`rag-sync`、`rag-search`、`rag-answer`、`layered-answer`、`wiki-compile`、`rag-health` CLI 命令，以及对应 MCP tools，使 Agent 能将分层检索与 Wiki 编译作为工具调用。
- 实现 `evaluation.py` 评测 runner，支持 YAML eval cases，对 workflow、RAG search、RAG answer、layered answer 执行 must_contain / must_not_contain / must_retrieve / must_cite / must_not_write 等规则断言，并输出 Markdown 评测报告。
- 采用 `uv` 管理 Python 环境与测试，补充 sample vault、workflow 单测、RAG 单测、CLI 路由测试、MCP tool wrapper 测试和评测 runner 测试。

### 面试讲述版

这个项目是我基于开源 Agent 框架 Nanobot 做的一次二次开发。我没有把它做成传统
纯 RAG 问答系统，而是把目标定义为“本地 Obsidian Markdown Wiki 的治理、检索、回答和评测”。
知识库遵循 `raw/`、`wiki/`、`TheSchema.md` 的 schema-driven 范式：`raw/` 保存原始资料，
`wiki/` 保存结构化页面，`TheSchema.md` 描述规则和工作流。

我实现了三个核心工作流：Ingest 负责把 `raw/` 中的 Markdown/Text 资料沉淀为
`wiki/sources/`、`wiki/concepts/`、`wiki/entities/` 页面；Query 只基于 `wiki/index.md`、Obsidian search 和 Markdown 页面做
规则化上下文汇总；Lint 负责检查 frontmatter、summary、wikilink、孤立页面和无出链页面。
在此基础上，我补充了 Chroma-backed RAG 与分层路由层：raw 作为实时原始素材和兜底检索库，
wiki 作为沉淀后的结构化知识大脑。用户问题会先经过路由判断：固定业务问题优先查 Wiki，
实时/临时问题走 raw RAG，复杂综合问题走 Wiki + raw 双路融合，Wiki 无结果时自动降级到 raw。
生成阶段会融合 Wiki 标准知识和 RAG 原始片段，输出引用标注、路径对齐和差异来源，降低幻觉风险。

安全方面，我设计了 VaultGuard：任何文件写入都必须经过路径归一化和权限校验，禁止路径穿越、
禁止写 vault 外路径、禁止写 `raw/`，默认 dry-run，只有显式 `--execute` 才能写入 `wiki/`，
并且所有写入都会追加到 `wiki/log.md`。RAG 索引缓存也只允许写到 `wiki/.nanobot/`，不会污染
`raw/`。最后我把它以最小侵入方式接入 Nanobot，新增 `obsidian_wiki` 与 `obsidian_rag_*`
MCP tools，Nanobot 通过 tool 参数或 `NANOBOT_OBSIDIAN_VAULT_PATH` 获取 vault，不会直接操作文件，
而是复用同一条安全调用链。

评测方面，我设计了一个轻量 Eval Runner，用 YAML 描述 Agent 基础功能、知识库 Workflow、RAG 和分层回答
用例，自动执行任务并检查工具输出、文件写入、RAG 召回、引用是否存在和禁用内容是否出现，最终生成
Markdown 评测报告。这让我可以把项目从“实现 Agent 能力”推进到“持续评估 Agent 是否可靠”。
