---
schema: bubblevan/v1
id: doc-hi-agent-mcp-host-todo
content_kind: project_roadmap
title: Hi-Agent MCP Host V1 — TO BE Done
date: 2026-08-26
updated: 2026-08-26
status: active
visibility: public
summary: Hi-Agent 从 Mini-MCP 协议学习转向 MCP Host、ToolRegistry 和 Context Selector 集成的可验证学习路线。先完成一个单 Server 端到端闭环，再进入 A2A。
topics: [Agent, MCP, Agent Harness, Tool Registry, Context Engineering, Roadmap]
projects: [hi-agent]
authors: [bubblevan]
---

# Hi-Agent MCP Host V1 — TO BE Done

## 0. 当前结论

状态：active

当前主线不是继续扩展 Mini-MCP，也不是立刻跳到 A2A，而是把已经学过的 MCP wire contract 接到 Hi-Agent 的运行时：

    官方 MCP SDK
          ↓
    Hi-Agent MCP Host
          ↓
    MCP Manager
          ↓
    Tool Catalog
          ↓
    Tool Adapter
          ↓
    ToolRegistry
          ↓
    Context Selector
          ↓
    Permission Policy
          ↓
    Executor + Trace
          ↓
    LLM

A2A 的进入条件是：上面这条链路至少有一个可测试的纵向切片，而不是只有若干孤立的类。

## 1. 为什么下一步不是马上 A2A

Mini-MCP 和 Mini-MRTR 已经回答了这些协议问题：

- 一个无 session 的现代 MCP 请求如何表达；
- server/discover、tools/list、tools/call 的 raw wire 形状；
- resultType、serverInfo、clientCapabilities 和 HTTP routing headers 的位置；
- structuredContent、outputSchema、分页和 cache hints 的基本边界；
- MRTR 如何通过 input_required 和重发请求完成多轮交互。

但 Hi-Agent 还需要回答更贴近 Harness 的问题：

- 多个 MCP Server 的工具如何进入一个统一目录；
- 工具 schema 如何避免全部塞进上下文；
- Context Selector 如何选择工具、解释选择理由并控制 token 预算；
- policy 如何阻止危险工具被模型直接调用；
- MCP 的协议错误、工具错误、权限拒绝如何被区分；
- 一次工具调用如何留下可追踪的 trace。

这些问题正是从“会调用协议”到“会构建 Agent Runtime”的关键一步。A2A 会增加 Agent Card、Task、Artifact、长任务状态和跨 Agent 失败处理；如果 Host 内部的能力目录和执行边界还没有稳定，A2A 只会把不清晰的边界扩大。

## 2. Mini-MCP 的新定位

Mini-MCP 现在是学习夹具，不是 Hi-Agent 的生产协议栈。

它保留在仓库中的用途：

1. 作为 2026 MCP 关键 wire contract 的最小可读实现；
2. 作为 raw wire contract tests 的本地测试服务器；
3. 作为 Host Manager 的 fake MCP Server；
4. 作为官方 SDK differential test 的对照端；
5. 作为学习博客中解释协议演进的实验材料。

当前已经完成的学习范围：

- stateless core；
- server/discover；
- tools/list；
- deterministic ordering；
- pagination；
- ttlMs 和 cacheScope；
- tools/call；
- resultType；
- 每请求 metadata；
- serverInfo；
- structuredContent 的 JSON 值；
- outputSchema 的教学子集校验；
- HTTP protocol、method、name headers；
- HeaderMismatch 和 UnsupportedProtocolVersion；
- raw wire contract tests；
- 独立 Mini-MRTR。

明确不再从 Mini-MCP 继续扩展完整 SDK：

- 不实现完整 JSON Schema 2020-12 validator；
- 不补齐全部 Resources、Prompts、Authorization 和 Extensions；
- 不把 Mini-MRTR 变成生产级任务系统；
- 不复制官方 SDK 的全部 transport、认证、重试和类型系统；
- 不让 Hi-Agent 的业务代码直接依赖 Mini-MCP 的内部类。

以后只有满足以下至少一项，才允许修改 Mini-MCP：

- 验证一个明确的 2026 wire contract；
- 暴露官方 SDK differential test 的差异；
- 支持 Host 集成测试；
- 帮助解释一个协议边界。

## 3. V1 目标和非目标

### 3.1 V1 目标

用官方 MCP Python SDK 接入一个本地 MCP Server，并完成：

    用户任务
      ↓
    Context Selector 选择工具
      ↓
    Permission Policy 判断
      ↓
    Tool Adapter 转换调用
      ↓
    MCP Manager 执行
      ↓
    ToolRegistry 统一返回
      ↓
    Trace 记录完整链路

第一版只需要两个只读工具：

- read_file；
- grep_code。

第一版应能回答：

    搜索项目中所有 Mini-MCP 相关代码，并总结它们的协议边界。

### 3.2 V1 非目标

- 暂不实现 A2A、ANP 或多 Agent 协作；
- 暂不做 OAuth/OIDC、mTLS、multi-tenancy；
- 暂不做工具市场、远程 Server 自动发现和动态安装；
- 暂不做完整 planner、workflow engine 或 autonomous loop；
- 暂不把所有工具 schema 永久注入 system prompt；
- 暂不把 Mini-MCP 作为官方 SDK 的替代品；
- 暂不为了“看起来完整”扩展大量协议功能。

## 4. 建议目录

先检查 Hi-Agent 已有目录和抽象，能复用就不重复建立：

    D:\MyLab\hi-agent\
    ├── protocols\
    │   └── mcp\
    │       ├── manager.py
    │       ├── adapter.py
    │       ├── catalog.py
    │       ├── policy.py
    │       └── errors.py
    ├── tools\
    │   └── registry.py
    ├── context\
    │   └── tool_selector.py
    ├── runtime\
    │   ├── executor.py
    │   └── trace.py
    ├── tests\
    │   └── protocol_lab\
    │       ├── test_mcp_manager.py
    │       ├── test_mcp_catalog.py
    │       ├── test_mcp_adapter.py
    │       ├── test_mcp_policy.py
    │       ├── test_mcp_selector.py
    │       └── test_mcp_host_e2e.py
    └── docs\
        └── protocol-lab\
            └── decisions\
                └── mcp-host-decisions.md

目录只是目标形状，不要求一次性创建全部文件。每完成一个 P 阶段，再落盘对应的最小代码和测试。

## 5. P0：冻结学习边界

### 子任务

- [x] 保留 Mini-MCP 作为协议学习夹具；
- [x] 保留独立 raw wire contract tests；
- [x] 保留独立 Mini-MRTR；
- [x] 在实验文档中记录已覆盖和未覆盖的 MCP 能力；
- [x] 写下官方 SDK 与 Mini-MCP 的边界；
- [x] 规定 Hi-Agent Host 不直接调用 Mini-MCP 内部实现；
- [x] 规定 ToolRegistry 只接收 Hi-Agent 自己的统一工具对象。

### 产物

- D:\MyLab\hi-agent\docs\protocol-lab\experiments\mini-mcp-2026.md
- D:\MyLab\hi-agent\docs\protocol-lab\decisions\mcp-host-decisions.md

### 完成标准

能用一句话解释：

    Mini-MCP 用来学习和测试协议；
    官方 SDK 用来承载 Host 集成；
    Hi-Agent 自己实现的是 Manager、Adapter、Catalog、Selector、Policy 和 Trace。

## 6. P1：盘点 Hi-Agent 现有接口

这是开始写 Host 之前必须完成的代码考古。

### 子任务

- [x] 找到当前 Tool 的抽象和输入输出格式；
- [x] 找到当前 ToolRegistry 的注册、查找和执行入口；
- [x] 找到当前 Context Selector 的输入、输出和 token 预算接口；
- [x] 找到当前 Executor 或 Agent loop 的工具调用边界；
- [x] 找到错误类型、重试和取消机制；
- [x] 找到 trace、logging 或 observation 的现有入口；
- [x] 确认同步/异步约定；
- [x] 确认 schema 是 dict、Pydantic model 还是其他类型；
- [x] 确认名称冲突和工具覆盖的现有行为；
- [x] 记录不能复用的接口以及原因。

### 产物

D:\MyLab\hi-agent\docs\protocol-lab\decisions\mcp-host-decisions.md

至少写清楚以下映射：

    MCP Manager       = 连接和刷新外部 Server
    Tool Catalog      = 保存外部能力的元数据
    Tool Adapter      = MCP 工具到 Hi-Agent Tool 的转换边界
    ToolRegistry      = Agent 内部统一查找入口
    Context Selector  = 任务相关工具选择入口
    Policy             = 执行前安全判断
    Executor           = 真正发起调用
    Trace              = 解释选择和失败发生在哪一层

### 完成标准

不新增代码也能指出：当前项目中哪个对象负责连接、目录、选择、授权、执行和观测。如果一个职责没有现成对象，记录为待新增，而不是先复制一套平行架构。

## 7. P2：实现单 Server MCP Manager

第一条真正的实现切片只连接一个本地 MCP Server。

### 子任务

- [x] 选择官方 MCP Python SDK 的稳定 API；
- [x] 建立一个明确的 Server 配置对象；
- [x] 建立连接、discover、list tools、close 的生命周期；
- [x] 保存 Server identity、protocol version 和 capabilities；
- [x] 保存 tools/list 的 ttlMs、cacheScope 和 discovered_at；
- [x] 支持显式 refresh；
- [x] 区分连接失败、协议错误和 Server 返回的 tool error；
- [x] 为断开和重复 refresh 写测试；
- [x] 为最小 async/sync 约定写一条决策记录。

Manager 不负责工具选择、Prompt 注入、写操作确认或业务结果解释。它只负责：

    server config
      → connect
      → discover
      → list
      → call
      → refresh
      → close

### 产物和完成标准

- D:\MyLab\hi-agent\protocols\mcp\manager.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_mcp_manager.py

一个测试能够证明：Manager 连接本地 Server 后，可以得到 Server identity、工具列表和结构化调用结果。

## 8. P3：建立 Tool Catalog 和命名空间

MCP Server 的工具不能未经整理直接进入 Agent 上下文。

### 每个 Catalog entry 至少记录

- server_id；
- server_name；
- server_version；
- original_tool_name；
- canonical_tool_name；
- description；
- inputSchema；
- outputSchema；
- ttlMs；
- cacheScope；
- read_only / write / dangerous 分类；
- discovered_at；
- 可选的 source、tags 和 estimated_schema_tokens。

### 命名规则

建议先采用：

    filesystem.read_file
    filesystem.grep_code
    github.get_issue

canonical name 用于 Hi-Agent 内部路由，original name 用于发回 MCP Server。调用链必须保留两者，不能只保存一个字符串。

### 子任务

- [x] 定义 Catalog entry；
- [x] 定义 server_id 生成和持久化规则；
- [x] 定义 canonical name 规则；
- [x] 定义同名工具的冲突处理；
- [x] 定义 Server 断开后的条目失效策略；
- [x] 定义 schema 和 cache hints 的保存方式；
- [x] 保持稳定排序；
- [x] 测试新增、刷新、移除和重复 Server。

### 产物和完成标准

- D:\MyLab\hi-agent\protocols\mcp\catalog.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_mcp_catalog.py

给定 canonical name，系统能稳定追溯到：

    canonical_tool_name
      → server_id
      → original_tool_name
      → 当前连接

## 9. P4：实现 Tool Adapter，接入 ToolRegistry

Adapter 是协议世界和 Hi-Agent 世界之间最重要的边界。

    Hi-Agent Tool call
      → canonical name
      → Adapter
      → original MCP name + arguments
      → Manager
      → MCP Server
      → normalized Hi-Agent result

### 子任务

- [x] 将 MCP tool definition 转换为 Hi-Agent Tool；
- [x] 保留 canonical、original、server 三种身份；
- [x] 保留 inputSchema 和 outputSchema；
- [x] 统一 text content 和 structuredContent；
- [x] 保留 isError；
- [x] 将 resultType、serverInfo 和 request metadata 留在协议层；
- [x] 将协议错误转换为明确的 Hi-Agent 错误；
- [x] 将工具业务错误与 Adapter 错误区分；
- [x] 测试 list 到 register 的完整过程；
- [x] 测试调用参数不能被错误改名或丢失。

### 完成标准

Agent 只调用 Hi-Agent Tool，不需要知道 MCP 的 headers、resultType、分页或 requestState。反过来，Adapter 能把一次 Hi-Agent 调用准确还原成 MCP Manager 所需的 Server 和 original tool。

## 10. P5：把 Context Selector 接到工具目录

这是 MCP 与 Hi-Agent Context Engineering 真正相交的地方。

不要把所有 tools/list 结果永久注入模型上下文：

    全量工具 schema
      → context 膨胀
      → tool selection 变差
      → token 成本和 cache 稳定性变差

目标是：

    Tool Catalog
      → candidate retrieval
      → relevance filtering
      → permission filtering
      → token budget
      → selected tool schemas

### 子任务

- [x] 让 Selector 读取 Catalog，而不是读取 MCP Server；
- [x] 定义任务文本到工具候选的输入格式；
- [x] 定义 name、description、tags 和 schema 的相关性信号；
- [x] 支持 permission 过滤；
- [x] 支持 token budget；
- [x] 返回 selected、dropped 和每个条目的 reason；
- [x] 记录 schema token 估算；
- [ ] 区分 stable prefix 和 dynamic tail；
- [ ] 让 catalog cache 与 selection cache 分开；
- [ ] 测试空目录、单工具、同名工具和超预算；
- [ ] 测试 refresh 后旧条目不会继续被选择。

### 验收场景

任务：

    搜索项目中所有 Mini-MCP 相关代码，并总结协议边界。

期望：

- 选择 filesystem.grep_code；
- 可能选择 filesystem.read_file；
- 不把无关的 GitHub 写工具注入上下文；
- 能解释为什么选择和丢弃某个工具；
- 选择结果可被 trace 记录。

### 产物

- D:\MyLab\hi-agent\context\tool_selector.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_mcp_selector.py
- D:\MyLab\hi-agent\docs\protocol-lab\experiments\mcp-tool-selection.md

## 11. P6：建立 MCP 调用 Policy 和 Executor 边界

权限判断必须发生在调用前，不能把危险判断交给模型自觉完成。

### 最小分类

    READ_ONLY
    WRITE
    DANGEROUS

### 默认行为

- READ_ONLY：可以自动执行；
- WRITE：需要显式确认或项目策略允许；
- DANGEROUS：默认拒绝；
- 未知工具：默认不自动放行。

### 子任务

- [x] 定义工具风险分类；
- [x] 定义 Policy 输入；
- [x] 在 Adapter/Executor 之前执行 Policy；
- [x] 区分 policy denied、MCP tool failed、transport failed；
- [x] 测试只读工具自动放行；
- [x] 测试写工具需要确认；
- [x] 测试危险工具默认拒绝；
- [x] 测试权限拒绝不会真的触发 MCP call；
- [x] 测试异常时默认 fail closed。

### 完成标准

任何一次调用都能回答：

    谁选择了这个工具？
    依据什么策略放行？
    实际是否发出了 MCP 请求？
    失败发生在 Policy、Adapter、Transport 还是 Server？

## 12. P7：接入 Trace 和错误语义

最小 trace 字段：

- trace_id；
- request_id；
- server_id；
- server_name；
- canonical_tool_name；
- original_tool_name；
- selected_by；
- selection_reason；
- policy_decision；
- started_at；
- duration_ms；
- resultType；
- isError；
- output validation status；
- final status。

### 错误分类

    selection_error
    policy_denied
    catalog_stale
    connection_error
    protocol_error
    tool_error
    output_validation_error
    timeout
    cancellation

### 子任务

- [x] 统一 trace event；
- [x] 不记录完整敏感 arguments；
- [x] 记录 Server 和 canonical tool 身份；
- [x] 记录 selected/dropped 理由；
- [x] 记录 resultType 和 isError；
- [x] 测试成功、拒绝、协议错误和工具错误；
- [ ] 为超时和取消预留状态。

### 完成标准

失败测试不仅断言“抛了异常”，还断言失败层级和可诊断字段正确。

## 13. P8：完成单 Server 端到端闭环

端到端流程：

    用户请求
      ↓
    Selector 选择 grep_code
      ↓
    Policy 判定 READ_ONLY
      ↓
    Registry 找到 canonical tool
      ↓
    Adapter 还原 original MCP tool
      ↓
    Manager 发起 tools/call
      ↓
    Server 返回 structured result
      ↓
    Registry 统一结果
      ↓
    Trace 保存全过程

### 子任务

- [x] 启动官方 SDK in-process MCP Server；
- [x] Manager 完成 discover 和 list；
- [x] Catalog 注册两个工具；
- [x] Adapter 接入 ToolRegistry；
- [x] Selector 根据任务选工具；
- [x] Policy 放行只读工具；
- [x] Executor 完成调用；
- [x] Trace 记录完整链路；
- [x] 测试成功结果；
- [x] 测试工具错误；
- [x] 测试策略拒绝；
- [x] 测试 Server 断开；
- [x] 测试目录刷新后重新选择。

### 产物

- D:\MyLab\hi-agent\tests\protocol_lab\test_mcp_host_e2e.py
- D:\MyLab\hi-agent\docs\protocol-lab\experiments\mcp-host-e2e.md
- D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\2026-08-27-hi-agent-mcp-host.md

## 14. P9：与官方 SDK 做差分验证，然后停止扩展 Mini-MCP

差分测试不是比较 JSON 字符串完全相同，而是比较关键 contract：

- discovery 的身份和版本；
- tools/list 的稳定排序；
- pagination；
- ttlMs 和 cacheScope；
- tools/call 的成功结果；
- resultType；
- serverInfo；
- structuredContent；
- tool error 和 protocol error；
- HTTP header/body mismatch；
- Mini-MRTR 的 input_required 语义。

### 子任务

- [x] 选择官方 SDK 的固定版本；
- [x] 为相同输入准备 Mini-MCP 和官方 SDK 两个 Server；
- [x] 规范化动态字段；
- [x] 比较关键字段和错误语义；
- [x] 记录不能比较的实现差异；
- [x] 记录 SDK 版本和实验环境；
- [x] 修复真正的 contract 差异；
- [x] 若差异只是教学简化，写明原因而不是继续复制 SDK。

### 产物

D:\MyLab\hi-agent\docs\protocol-lab\reports\mcp-sdk-differential.md

### 完成标准

能说清楚：

    哪些行为必须和官方 SDK 一致；
    哪些行为只是 Mini-MCP 的教学简化；
    Hi-Agent 自己新增的价值位于 SDK 之上哪些层。

## 15. MCP Host V1 Definition of Done

- [x] 一个本地 MCP Server 可被官方 SDK 连接；
- [x] Manager 能 discover、list、call、refresh、close；
- [x] Tool Catalog 能保存 Server 和工具身份；
- [x] Adapter 能接入 Hi-Agent ToolRegistry；
- [x] canonical name 和 original name 可以双向追溯；
- [x] Context Selector 能按任务选择工具；
- [x] Selector 有 token budget 和选择理由；
- [x] Policy 能放行只读、拦截危险、控制写操作；
- [x] Executor 能执行并区分失败层级；
- [x] Trace 能解释一次调用；
- [x] 至少有成功、工具失败、权限拒绝、连接失败测试；
- [x] raw wire contract tests 保持通过；
- [x] official SDK differential report 已完成；
- [x] MCP Host 博客学习笔记已落盘；
- [x] 不再以补齐 Mini-MCP 功能作为下一阶段目标。

完成这些以后，才进入 A2A。

## 16. A2A 进入门槛和后续路线

### 16.1 进入门槛

开始 A2A 前，至少能独立解释：

- MCP 是 Agent 调用外部能力；
- A2A 是 Agent 委托目标给另一个 Agent；
- 为什么 Agent 不能只被建模成一个 Tool；
- ToolRegistry 和 Agent Card 的职责差异；
- 一次 tools/call 和一个 Task 的生命周期差异；
- policy、trace 和 artifact 在跨 Agent 场景如何延伸。

工程上至少完成：

- MCP Host 单 Server 端到端闭环；
- ToolRegistry 动态注册和检索；
- Context Selector 动态工具选择；
- Policy 和 Trace；
- 一个官方 SDK differential test；
- 能够明确区分 Tool result 和 Agent Artifact。

### 16.2 A2A 学习切片

A2A 阶段不做 calculator demo，直接沿用 Hi-Agent 的真实能力：

    Research Agent
          │
          │ A2A Task
          ▼
    Coding Agent
       ├── MCP filesystem
       ├── MCP GitHub
       └── CLI pytest
          │
          ▼
       Artifact

最小 A2A 纵向切片：

- Agent Card discovery；
- Message；
- Task 创建；
- WORKING；
- Artifact 产生；
- COMPLETED；
- 一个失败状态；
- polling 或 streaming 二选一；
- 记录 delegated_by、task_id 和 artifact_id。

A2A 之后再考虑 push notification、认证、version negotiation 和多 Agent 路由。

## 17. 建议博客落盘顺序

- [x] D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\2026-08-25-agent-protocol-map.md
      协议地图、Mini-MCP、Mini-MRTR 和学习判断；
- [x] D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\2026-08-27-hi-agent-mcp-host.md
      Manager、Adapter、ToolRegistry 的第一条闭环；
- [x] D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\2026-08-28-mcp-tool-catalog-selector.md
      Catalog、schema budget、dynamic tool selection；
- [ ] D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\2026-08-29-hi-agent-mini-a2a.md
      A2A Task/Artifact 最小实验；
- [ ] D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\2026-08-30-mcp-a2a-composition.md
      MCP inside agents、A2A between agents 的组合。

每篇博客都应包含：

- 这次要回答的一个问题；
- 一个最小实验；
- raw input/output 或 trace；
- 一个失败案例；
- 当前实现和生产协议的边界；
- 下一步是否继续、停止或转向。

## 18. 下一次实际执行顺序

不要一次创建整个目录。按以下顺序推进：

1. 完成 P1：盘点当前 ToolRegistry、Context Selector、Executor 和 Trace；
2. 写 mcp-host-decisions.md，先固定复用边界；
3. 完成 P2：只连接一个本地 MCP Server；
4. 完成 P3/P4：把两个只读 MCP tools 注册成 Hi-Agent tools；
5. 完成 P5：让 Selector 从 Catalog 选择工具；
6. 完成 P6/P7：加 Policy 和 Trace；
7. 完成 P8：跑通端到端；
8. 完成 P9：做一次官方 SDK differential test；
9. 写 MCP Host 博客；
10. 通过 A2A 进入门槛后，再开始 A2A Task/Artifact。

## 19. A2A 门槛审计（2026-08-26）

结论：已满足文档规定的 A2A 进入门槛，可以转向 A2A Task/Artifact 最小实验。

- [x] MCP Host 单 Server 端到端闭环；
- [x] ToolRegistry 动态注册和检索；
- [x] Context Selector 动态工具选择；
- [x] Policy 和 Trace；
- [x] 官方 SDK differential test；
- [x] 能区分 Tool result 和未来的 Agent Artifact；
- [x] 博客包含实际代码、失败排查和协议八卦；
- [ ] 多 Server 真实部署；
- [ ] OAuth、mTLS、multi-tenancy；
- [ ] A2A streaming、push notification 和认证；
- [ ] ANP discovery、DID 和 trust。

门槛的含义不是 MCP Host 已经生产就绪，而是已经足够稳定，可以把下一个研究问题
从“怎么接外部能力”切换为“什么时候应该把目标委托给另一个 Agent”。

下一阶段入口：

    Research Agent
          ↓ A2A Task
    Coding Agent
          ↓ MCP
    filesystem / GitHub / pytest
          ↓
       Artifact

## 20. 给未来自己的提醒

不要因为 A2A 更像“多 Agent”就跳过 MCP Host。MCP Host 这一阶段会把四个重要映射真正落到代码：

    external capability → runtime integration
    tool catalog        → context selection
    user intent         → permission policy
    tool result         → trace and diagnosis

A2A 阶段再增加：

    agent capability     → Agent Card
    delegated intent     → Task
    long-running result  → Artifact
    remote progress      → streaming/polling

因此当前答案是：

    MCP Host V1 已经完成门槛；
    下一步正式转向 A2A 的 Agent Card → Task → Artifact 切片；
    MCP 继续作为 Coding Agent 内部的工具协议。

## 21. Mini-A2A V1 进度

截至 2026-08-26，Mini-A2A 已完成第一条教学切片：

- [x] AgentCard；
- [x] Message 和 Part；
- [x] Task 和 TaskStatus；
- [x] Artifact；
- [x] GetAgentCard；
- [x] SendMessage；
- [x] GetTask；
- [x] SUBMITTED → WORKING → COMPLETED；
- [x] WORKING → FAILED；
- [x] terminal state transition guard；
- [x] Message mode / Task mode stream guard；
- [x] Coding Agent → MCP Host → Artifact bridge。

当前仍然刻意不做：

- [ ] 官方 A2A SDK differential test；
- [ ] HTTP binding；
- [ ] streaming over network；
- [ ] authentication、JWS、OAuth、mTLS；
- [ ] push notification、ListTasks、CancelTask；
- [ ] multi-tenancy。

下一阶段可以从 Mini-A2A V1 切换到官方 SDK 对照，再决定是否实现真实
Research Agent → Coding Agent 委托，而不是继续扩展教学协议的边角功能。
