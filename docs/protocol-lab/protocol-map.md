# Hi-Agent Agent Protocol Map

## 1. 本文目的

本文用于建立 Hi-Agent 学习智能体通信协议时的第一版心智模型。

本阶段不实现协议，而是回答：不同技术位于哪一层、解决什么问题、为什么 Hi-Agent 应该优先建设 MCP Host。

## 2. 总体架构

    User
      │
      ▼
    LLM
      │ Tool Calling / Function Calling
      ▼
    Hi-Agent Host / Harness
      ├── CLI / Shell
      ├── Filesystem primitives
      ├── Native APIs
      ├── Local Tool Registry
      └── MCP Client
            │
            ▼
          MCP Servers
            ├── REST API
            ├── Database
            ├── CLI
            ├── Filesystem
            └── SaaS

当任务需要另一个自主 Agent 时，调用路径扩展为：

    Hi-Agent Coordinator
            │ A2A Task
            ▼
    Specialist Agent
            │ MCP / CLI / API
            ▼
    External capabilities
            │
            ▼
    Artifact / Task Result

当系统中存在多个候选 Agent 时，增加发现层：

    Agent Description
            ↓
    .well-known / Discovery
            ↓
    Identity / Trust
            ↓
    Capability Matching
            ↓
    Endpoint Selection
            ↓
    A2A Task or other request

## 3. 七个概念的边界

| 概念 | 所在层次 | 回答的问题 |
|---|---|---|
| CLI | 程序接口 | 人或程序如何从命令行操作一个程序？ |
| API | 服务接口 | 程序如何调用另一个服务？ |
| Function Calling | 模型交互 | 模型如何表达“我要调用函数 X，参数是 Y”？ |
| Tool | Agent 能力抽象 | Agent 可以调用哪些能力？ |
| MCP | Agent 能力通信协议 | Agent 如何发现、理解和调用外部能力？ |
| A2A | Agent 间通信协议 | 一个 Agent 如何委托任务给另一个 Agent？ |
| ANP | Agent 网络发现与信任 | Agent 如何发现、验证和连接其他 Agent？ |

## 4. CLI 与 MCP 的关系

CLI 和 MCP 不是二选一。

例如，Git CLI 可能提供：

    git status
    git commit
    git push

MCP Server 可以把这些能力包装成可发现、带 schema 的工具：

    get_status()
    commit(message)
    push(remote, branch)

内部调用链可能是：

    Agent
      │ MCP
      ▼
    Git MCP Server
      │ subprocess
      ▼
    git CLI
      ▼
    Git repository

也可以完全不使用 MCP：

    Agent
      ↓
    Shell Tool
      ↓
    git status

MCP 的价值在于，它把面向人的、非结构化的操作入口，包装成 Agent 可以动态发现和校验的能力描述：

    Human-oriented interface
              ↓
    Structured / discoverable capability

## 5. MCP 的核心心智模型

### 5.1 Host、Client、Server

    Host
      ├── MCP Client 1 ─── MCP Server A
      ├── MCP Client 2 ─── MCP Server B
      └── Local Tool Registry

- Host：Claude Desktop、Cursor、Hi-Agent Harness 等承载 Agent 运行的应用；
- MCP Client：Host 内部维护的协议连接；
- MCP Server：对外暴露工具、资源或其他能力的服务。

因此，“Hi-Agent 使用 MCP”更准确地说是：

> Hi-Agent 作为 Host，管理一个或多个 MCP Client，并把发现到的能力接入自己的 Runtime。

### 5.2 能力发现、工具发现与调用

2026-07-28 核心不再要求 initialize / initialized 握手。客户端可以通过 server/discover 获取服务能力；随后通过 tools/list 获取工具目录，再通过 tools/call 执行工具。

    server/discover
        ↓
    supportedVersions + capabilities
        ↓
    tools/list
        ↓
    name + description + input schema
        ↓
    Hi-Agent Tool Catalog
        ↓
    Context Selector
        ↓
    LLM 判断调用哪个工具
        ↓
    tools/call
        ↓
    structured result / error

### 5.3 MCP 与 Context Engineering

假设连接多个 MCP Server：

    50 个 Server × 每个 20 个工具 = 1000 个工具 schema

如果把全部 schema 永久注入上下文，会产生：

- 工具选择困难；
- schema 占用大量上下文；
- prompt 前缀不稳定；
- 工具目录重复传输；
- 错误工具被模型误选。

因此 Hi-Agent 需要将 MCP Tool Catalog 与 Context Selector 连接起来：

    MCP Tool Catalog
            ↓
    Metadata / Index
            ↓
    Task-aware Tool Retrieval
            ↓
    Selected Tool Schemas
            ↓
    LLM Context

这正是 MCP 与 Hi-Agent 当前 Context / Harness 方向的交叉点。

## 6. A2A 的核心心智模型

MCP 更接近：

    请替我执行能力 X

A2A 更接近：

    请你自主完成目标 Y，并返回最终成果

A2A 的最小对象关系：

    Agent Card
        ↓ 描述能力
    Message
        ↓ 传递请求
    Task
        ↓ 表示长期工作
    Artifact
        ↓ 表示结果产物
    Task lifecycle
        ↓ 表示状态变化

最小生命周期：

    Task Created
        ↓
    WORKING
        ↓
    Artifact Produced
        ↓
    COMPLETED

因此 Agent 不是一个普通 Tool：

- Agent 可以内部调用多个工具；
- Agent 可以执行多步推理；
- Agent 可能长时间运行；
- Agent 需要报告进度和状态；
- Agent 的结果可能是 patch、报告、文件或其他 Artifact。

## 7. ANP 的核心心智模型

ANP 关注的问题不是“如何执行某个工具”，而是：

    网络中有哪些 Agent？
    它们分别能做什么？
    我如何找到合适的 Agent？
    我如何确认它是谁？
    我如何信任它？

最小流程：

    Agent Description
        ↓
    .well-known discovery
        ↓
    DID / public key resolution
        ↓
    Identity verification
        ↓
    Capability matching
        ↓
    Endpoint selection
        ↓
    Authenticated request

需要特别区分：

    ANP：找到谁、验证谁、选择谁
    A2A：和选中的 Agent 协作
    MCP：调用 Agent 或 Host 所需要的工具能力

## 8. Hi-Agent 的协议接入位置

    LLM
      ↓
    Context Selector
      ↓
    Tool Registry
      ├── Native Tools
      └── MCP Adapter
            ↓
        MCP Manager
            ↓
        MCP Servers

A2A 与 ANP 位于更高的任务协作层：

    Coordinator Runtime
      ├── Local Tool Registry
      ├── MCP Manager
      ├── A2A Task Bridge
      └── ANP Discovery / Identity

## 9. 当前设计决策

### 决策一：先做 MCP Host，不做完整 MCP SDK

原因：Hi-Agent 的核心价值在工具目录、上下文选择、权限、执行和追踪，而不是重新实现 JSON-RPC 或完整传输栈。

### 决策二：Mini-MCP 只用于学习

Mini-MCP 只验证：

    declaration → discovery → schema → call → result / error

完成后切换到官方 SDK。

### 决策三：A2A 围绕 Task 和 Artifact 学习

不把 A2A 简化为 execute_skill()，优先理解长期任务、状态和产物。

### 决策四：ANP 以协议阅读和最小 discovery 实验为主

不把简单的 Python 服务注册表当成真实 ANP 网络。

## 10. 下一步

1. 盘点 Hi-Agent 当前 ToolRegistry、Context Selector 和执行器；
2. 完成 CLI / API / Function Calling / MCP / A2A / ANP 对比；
3. 设计 Mini-MCP 的 read_file 和 grep_code；
4. 为 Mini-MCP 写最小测试目标；
5. 记录第一篇博客：从 CLI 到 MCP Host。
