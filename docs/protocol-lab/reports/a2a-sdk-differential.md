# Mini-A2A 与官方 a2a-sdk v1 差分记录

日期：2026-08-26

## 目的

这份报告不比较两个实现的 JSON 字节是否相同，而比较它们是否表达了相同的
A2A 核心语义：

    AgentCard → Message → Task → Artifact → terminal state

Mini-A2A 是教学夹具；官方 SDK 1.1.2 负责真实 proto 类型、JSON-RPC route、
streaming 和 Task Store。

## 版本和环境

    package: a2a-sdk
    version: 1.1.2
    protocol: A2A v1.0
    transport tested: JSON-RPC over ASGI
    test: tests/protocol_lab/test_a2a_sdk_integration.py

## 对照表

| 语义 | Mini-A2A | 官方 SDK 集成 |
| --- | --- | --- |
| Agent discovery | AgentCard dataclass / get_agent_card() | /.well-known/agent-card.json + A2ACardResolver |
| 通信消息 | Message + Part | proto Message + helper new_text_message |
| 长任务 | Task / TaskStatus | proto Task / TaskStatus + InMemoryTaskStore |
| 状态推进 | transition_task() | TaskUpdater.start_work() / complete() / failed() |
| 交付物 | Artifact | TaskUpdater.add_artifact() |
| 流 | 本地状态/Artifact event | StreamResponse oneof payload |
| 执行行为 | 同步 AgentExecutor.execute() | 异步 AgentExecutor.execute(context, event_queue) |
| MCP 组合 | CodingAgentExecutor | MCPBackedA2AExecutor + asyncio.to_thread |

## 实际运行结果

    $ .venv\Scripts\python.exe -m pytest tests\protocol_lab\test_a2a_sdk_integration.py -q
    ..                                                               [100%]

事件 payload 顺序：

    task
    status_update
    artifact_update
    status_update

关键状态：

    TASK_STATE_SUBMITTED
    TASK_STATE_WORKING
    TASK_STATE_COMPLETED

结构化 Artifact 中的 MCP 证据：

    selected_tool = filesystem.grep_code
    trace.selected_by = official_a2a_coding_executor
    trace.status = completed

## 有意保留的差异

### 1. Mini-A2A 是同步、进程内 API

Mini-A2A Client 直接持有 Server 对象，目的是让状态转换和 stream 顺序
可被单元测试观察。官方 integration 则通过 Agent Card 和 JSON-RPC route
走真正的 SDK transport。

### 2. Mini-A2A 只实现四个状态

教学版只保留 SUBMITTED、WORKING、COMPLETED、FAILED。官方 SDK 还包含
input-required、auth-required、canceled、rejected 等中断或终止语义。

### 3. Mini-A2A 的 stream event 是独立 Python 对象

官方 SDK 使用 proto StreamResponse 的 oneof。这个差异不是语义冲突，
而是“教学对象模型”和“wire-ready 类型系统”的分层差异。

### 4. 官方 SDK 的 COMPLETED 不靠 Mini-A2A invariant

官方 SDK 通过 TaskUpdater 发布 Artifact 与 complete 事件；事件合法性和
Task Store 由 SDK handler 维护。Mini-A2A 则把“COMPLETED 必须有 Artifact”
显式集中在 transition_task()，让状态机本身成为学习对象。

## 本轮结论

Mini-A2A 已经完成它的职责：帮助理解对象、状态机和模式边界。官方 SDK
integration 已证明同一条 A2A 核心语义可以落到真实的 Agent Card、JSON-RPC、
EventQueue、Task Store 和 Client 上。

下一步不是继续复制 SDK，而是把 Research Agent 的任务委托场景接入 Hi-Agent
runtime，并为 delegated_by、task_id、artifact_id 和远端失败补观测字段。
