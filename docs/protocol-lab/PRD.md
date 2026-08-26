# Hi-Agent Protocol Lab

## 项目状态

- 版本：v0.1
- 状态：学习项目启动
- 负责人：Hi-Agent 学习者
- 目标日期：2026-09-01
- 关联章节：HelloAgents 第 10 章《智能体通信协议》

## 1. 项目背景

Hi-Agent 正在从单体 Agent、工具调用和上下文工程，继续走向 Agent Harness / Agent Runtime。

本项目不以完整复刻 MCP、A2A、ANP 的 SDK 为目标，而是通过最小实验理解协议边界，并把成熟协议接入 Hi-Agent 的运行时。

本项目遵循三个判断：

1. MCP 重点做 Host / Runtime 集成。
2. A2A 重点理解 Agent Card、Task、Artifact 和任务生命周期。
3. ANP 重点理解 Discovery、Identity、Trust 和 Endpoint 选择。

## 2. 项目目标

完成一个可解释、可验证的协议学习闭环：

    Hi-Agent Host
     ├── MCP：发现并调用外部工具
     ├── A2A：委托任务给另一个 Agent
     └── ANP：发现、验证和选择 Agent 服务

最终使用场景：

    Research Agent
          │ A2A Task
          ▼
    Coding Agent
          │ MCP
          ├── GitHub
          ├── filesystem
          └── pytest / CLI

## 3. 非目标

本项目暂不要求：

- 重写完整 MCP SDK；
- 重写完整 A2A SDK；
- 实现生产级 OAuth、mTLS、DID 基础设施和复杂路由；
- 逐行复刻 HelloAgents 第 10 章的全部示例；
- 将 ANP 教学用注册表扩展成真实的大规模 Agent 网络；
- 在基础通信闭环完成前实现投票、协商和复杂负载均衡。

## 4. 学习原则

每个子任务都必须经过以下循环：

    目标 → 心智模型 → 最小实验 → 失败场景 → 验证证据 → 学习笔记 → 下一步

每个阶段都要回答：

- 我学到了什么？
- 我实际验证了什么？
- 哪个地方失败了？
- 这个协议解决了什么问题？
- 它与 Hi-Agent 的哪个模块有关？
- 为什么下一步是当前选择，而不是继续扩大范围？

## 5. 目录和产物

    D:\MyLab\hi-agent\
    ├── docs\
    │   └── protocol-lab\
    │       ├── PRD.md
    │       ├── protocol-map.md
    │       ├── decisions\
    │       ├── experiments\
    │       └── reports\
    ├── protocols\
    │   ├── mcp\
    │   │   ├── mini_mcp\
    │   │   │   ├── protocol.py
    │   │   │   ├── client.py
    │   │   │   ├── server.py
    │   │   │   └── mrtr.py
    │   │   └── host\
    │   │       ├── manager.py
    │   │       ├── catalog.py
    │   │       ├── adapter.py
    │   │       ├── policy.py
    │   │       └── host.py
    │   └── a2a\
    │       └── mini_a2a\
    │           ├── models.py
    │           ├── protocol.py
    │           ├── client.py
    │           ├── server.py
    │           └── executor.py
    └── tests\
        └── protocol_lab\

博客学习笔记放在：

    D:\MyLab\Hugo\bubblevan.github.io\content\blog\2026\

博客是面向读者的学习总结；docs/protocol-lab/ 才是项目内部的设计和实验记录。

## 6. 子任务路线

### P0：项目盘点

目标：确认 Hi-Agent 已有的 Agent、ToolRegistry、Context Selector、错误处理和追踪能力。

产物：

- docs/protocol-lab/protocol-map.md
- Hi-Agent 当前能力和缺口清单

验收标准：能够在一张图上指出 MCP Host、Tool Registry、Context Selector 和执行器的关系。

### P1：协议地图

目标：区分 CLI、API、Function Calling、Tool、MCP、A2A、ANP。

产物：

- CLI / API / Function Calling / MCP / A2A / ANP 对比表
- 一条端到端调用链
- 一篇博客草稿：2026-08-25-agent-protocol-map.md

验收标准：能够解释为什么 CLI 和 MCP 不是二选一，以及 MCP Server 为什么可以在内部调用 CLI。

### P2：Mini-MCP

目标：亲手完成最小的 capability declaration、discovery、schema、call 和 error 闭环。

范围：

- server/discover
- tools/list
- tools/call
- 结构化结果
- 错误响应
- read_file
- grep_code

产物：

- protocols/mcp/mini_mcp/
- docs/protocol-lab/experiments/mini-mcp.md
- tests/protocol_lab/test_mini_mcp.py

验收标准：能通过 server/discover 获取能力，列出工具、读取 schema、成功调用工具，并对不存在的工具和错误参数给出可观察的错误。

### P3：MCP Host 接入

目标：使用官方 MCP SDK，并将 MCP 工具接入 Hi-Agent 的 ToolRegistry。

建议职责：

- MCP Manager：连接、生命周期、错误处理；
- Tool Adapter：MCP Tool 到 Hi-Agent Tool 的转换；
- Registry：注册、命名空间和冲突处理；
- Policy：权限、危险操作控制和审计。

验收标准：Hi-Agent 能连接至少一个 MCP Server，并把发现到的工具注册到自己的工具系统。

### P4：Tool Catalog 与 Context Selector

目标：解决大量 MCP tool schema 对上下文窗口、工具选择和 prompt cache 的影响。

至少比较：

- 所有工具始终注入；
- 根据任务动态检索工具。

记录：工具数量、schema 大小、选择准确性、漏选、误选、缓存和稳定前缀影响。

验收标准：能用实验记录说明为什么 MCP Tool Discovery 是 Context Engineering 问题。

### P5：Mini-A2A

目标：理解 Agent Card、Message、Task、Artifact 和任务生命周期。

最小生命周期：

    Agent Card → Send Message → Task Created → WORKING → Artifact → COMPLETED

验收标准：完成一次 Agent A → Agent B → Artifact 的协作，并能解释 Agent 为什么不只是一个 Tool。

### P6：A2A Bridge

目标：让 Hi-Agent 主 Agent 能够委托一个长期任务给另一个 Agent。

验收标准：返回结构化 Artifact，例如 patch、测试报告或研究报告，而不是只有一段普通字符串。

### P7：ANP Discovery

目标：理解 Agent Description、.well-known、DID、Identity、Trust 和 Endpoint 选择。

范围：只做两个 Agent 的最小 discovery 实验，不实现真实大规模网络。

验收标准：能区分服务发现、身份验证、能力匹配和实际调用四个步骤。

### P8：综合项目

目标：完成一个 Hi-Agent 作为 Host 的综合流程：MCP 访问工具，A2A 委托 Agent，ANP 模拟发现和选择 Agent。

验收标准：有架构图、时序图、一次完整请求记录、失败场景、权限边界和局限性说明。

## 7. 验收矩阵

| 能力 | 最低验收标准 | 证据 |
|---|---|---|
| 协议理解 | 能说明各协议的通信对象和边界 | protocol-map.md |
| Mini-MCP | 能完成 list / call / error | 实验记录和测试 |
| MCP Host | 能接入官方 SDK 并注册工具 | 运行日志和适配器设计 |
| Tool Context | 能动态选择工具并记录选择结果 | 对比实验 |
| Mini-A2A | 能完成 Task → Artifact | 生命周期记录 |
| ANP | 能解释 discovery 与 identity | discovery 实验 |
| 综合集成 | MCP + A2A + ANP 职责清晰 | 架构图和博客总结 |

## 8. 博客写作规范

每个重要阶段写一篇独立笔记，不写成代码流水账。统一包含：

1. 这篇文章要解决什么问题；
2. 我的心智模型；
3. 实验设计；
4. 实际调用链；
5. 失败和排查；
6. 如何验证；
7. 与 Hi-Agent 的关系；
8. 本阶段没有做什么；
9. 下一步。

博客初始序列：

    2026-08-25-agent-protocol-map.md
    2026-08-26-mini-mcp.md
    2026-08-27-hi-agent-mcp-host.md
    2026-08-28-mcp-tool-catalog-context.md
    2026-08-29-mini-a2a-task-artifact.md
    2026-08-30-hi-agent-a2a-bridge.md
    2026-08-31-anp-discovery-identity.md
    2026-09-01-hi-agent-protocol-integration.md

## 9. 完成定义

本项目完成的标准不是“实现了多少代码”，而是：

> 能解释协议为什么这样设计，能用最小实验验证核心抽象，能把成熟 SDK 接入 Hi-Agent，并能通过博客清晰说明设计取舍和失败经验。
