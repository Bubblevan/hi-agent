---
schema: bubblevan/v1
id: doc-hi-agent-a2a-todo
content_kind: project_roadmap
title: Hi-Agent A2A V1 — TO BE Done
date: 2026-08-26
updated: 2026-08-26
status: active
visibility: public
summary: Hi-Agent 在 MCP Host 门槛完成后，围绕 Agent Card、Task、Artifact 和远端委托建立官方 A2A v1 学习与工程路线。
topics: [Agent, A2A, MCP, Agent Infra, Task Lifecycle, Roadmap]
projects: [hi-agent]
authors: [bubblevan]
---

# Hi-Agent A2A V1 — TO BE Done

> 状态：Active / 第一条官方 SDK 集成已完成  
> 这是一份学习型 backlog，不是把 A2A 做成通用 orchestration framework 的产品排期。

## 0. 先写结论：Mini-A2A 已经收口

Hi-Agent 已经完成两层工作：

    protocols/a2a/mini_a2a/
        用同步、进程内代码理解 AgentCard、Message、Task、Artifact
        和最小状态机

    protocols/a2a/integration/
        用官方 a2a-sdk v1.1.2 实现 Agent Card discovery、
        JSON-RPC streaming、Task Store、MCP Host bridge 和 GetTask

因此下一步不是继续给 Mini-A2A 增加 HTTP、认证、更多状态或更多 binding。
下一步要回答的是：

> Research Agent 什么时候应该把目标委托给 Coding Agent？委托之后如何
> 观察远端任务、接收 Artifact、处理失败并把结果带回自己的 Context？

## 1. A2A V1 的定位

### 1.1 它要解决的问题

MCP 解决：

    Agent 内部如何发现和调用外部工具、数据或上下文能力

A2A 解决：

    一个独立 Agent 如何发现另一个 Agent、委托目标、观察 Task
    并接收最终 Artifact

Hi-Agent 的目标链路：

    Research Agent
        ↓ official A2A
    Coding Agent
        ↓ official MCP
    MCP Host
        ↓
    filesystem / GitHub / pytest
        ↓
    Artifact

### 1.2 它不是什么

A2A V1 不是：

- 把每个 Agent 包成一个没有状态的 Tool；
- 再写一套 JSON-RPC parser；
- 再复制一套 HTTP、gRPC、认证和序列化 SDK；
- 用 calculator demo 代替真实委托场景；
- 为了“多 Agent”而增加一个没有业务意义的 Agent Registry；
- 把远端 Agent 的所有内部 MCP tools 暴露到 Agent Card；
- 用任务数量或测试数量冒充互操作性质量。

### 1.3 时间分配建议

| 工作 | 建议占比 | 目的 |
| --- | ---: | --- |
| 阅读官方 spec、SDK migration 和 samples | 20% | 识别 v1 类型和 binding |
| Mini contract / raw event 实验 | 20% | 建立 Task/Artifact 心智模型 |
| 官方 SDK integration | 30% | 验证真实 Server/Client 组合 |
| Hi-Agent 委托 runtime | 20% | 建立路由、持久化、观测边界 |
| benchmark / failure drill | 10% | 判断是否值得继续扩展 |

如果大部分时间又花在复制 SDK，说明方向偏了。

## 2. 当前已完成状态

### 2.1 Mini-A2A 学习夹具

- [x] AgentCard；
- [x] AgentSkill；
- [x] Message 和 Part；
- [x] Task 和 TaskStatus；
- [x] Artifact；
- [x] AgentCard / Message / Artifact 基础校验；
- [x] SUBMITTED → WORKING → COMPLETED；
- [x] WORKING → FAILED；
- [x] terminal state 不可复活；
- [x] COMPLETED 必须包含 Artifact；
- [x] Message mode / Task mode stream 校验；
- [x] Coding Agent → MCP Host → Artifact bridge；
- [x] 中文教学注释和实验记录。

### 2.2 官方 A2A SDK 集成

- [x] 固定官方 a2a-sdk 1.x 依赖；
- [x] Agent Card 使用 v1 supported_interfaces；
- [x] /.well-known/agent-card.json discovery；
- [x] 官方 JSON-RPC route；
- [x] 官方 AgentExecutor 和 EventQueue；
- [x] TaskUpdater 发布 WORKING、Artifact 和 COMPLETED；
- [x] InMemoryTaskStore；
- [x] 官方 Client discovery 和 SendStreamingMessage；
- [x] GetTask 读回最终任务；
- [x] 官方 A2A → MCP Host → Artifact；
- [x] Mini-A2A 与官方 SDK 核心生命周期差分测试；
- [x] 终端运行日志和博客笔记。

### 2.3 当前明确未做

- [ ] Research Agent 业务编排；
- [ ] delegated_by / delegation policy；
- [ ] remote task persistence；
- [ ] timeout / retry / cancellation token；
- [ ] remote failure normalization；
- [ ] signed Agent Card；
- [ ] OAuth、mTLS；
- [ ] push notification；
- [ ] multi-tenancy；
- [ ] gRPC；
- [ ] ANP discovery、DID 和 trust。

这些未完成项不是当前核心切片的阻塞项。

## 3. 启动条件和暂停条件

### 3.1 A2A 主线启动条件

以下条件已经满足：

- MCP Host 有单 Server 端到端闭环；
- ToolRegistry 和 Context Selector 已经可测试；
- Policy 和 Trace 已经存在；
- Mini-A2A 已经覆盖 Task/Artifact 核心语义；
- 官方 a2a-sdk Server/Client 已经跑通；
- A2A 与 MCP 的边界已经写入代码和文档。

### 3.2 暂停条件

遇到下面情况时暂停新增功能，先写报告：

- 官方 SDK 升级导致 API 变化；
- Task stream 出现顺序、终态或 Artifact 丢失；
- 同步 MCP Host 阻塞 A2A event loop；
- 远端失败无法区分 transport、protocol、tool 和 policy；
- Task Store 只能返回当前状态，无法恢复历史或 Artifact；
- Agent Card 暴露了不应该暴露的内部工具信息；
- 为了测试而引入完整数据库、消息队列或多 Agent 框架。

## 4. P0：冻结 Mini-A2A 学习边界

### 子任务

- [x] 保持 Mini-A2A 为同步、进程内学习夹具；
- [x] 不向 mini_a2a 塞入官方 SDK import；
- [x] 用注释解释 Message、Task、Artifact 的职责差异；
- [x] 用状态机集中表达 terminal state；
- [x] 用 Artifact invariant 阻止伪成功；
- [x] 单独记录官方 SDK 与 Mini-A2A 的有意差异；
- [x] 为失败路径和 stream mixing 写测试。

### 产物

- D:\MyLab\hi-agent\protocols\a2a\mini_a2a\
- D:\MyLab\hi-agent\tests\protocol_lab\test_mini_a2a_contract.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_mini_a2a_lifecycle.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_mini_a2a_stream.py
- D:\MyLab\hi-agent\docs\protocol-lab\experiments\mini-a2a-v1.md

### 完成标准

能够用一句话解释：

    Mini-A2A 学 Task 生命周期；
    官方 SDK 负责真实协议 binding；
    Hi-Agent 自己负责 Agent runtime、委托策略、MCP Host 和观测。

## 5. P1：官方 SDK Server / Client 纵向切片

### 目标

把一个 Coding Agent 暴露为官方 A2A Server，把一个 Research Agent 的最小
调用方暴露为官方 Client。

### Server 子任务

- [x] 构造高层 Agent Card；
- [x] 使用 /.well-known/agent-card.json；
- [x] 只挂载 JSON-RPC route；
- [x] 实现官方 AgentExecutor；
- [x] 以 Task 作为 streaming 第一条事件；
- [x] 发布 WORKING 状态；
- [x] 通过 MCP Host 选择并执行只读工具；
- [x] 把 MCP result 和 trace 包装成 Artifact；
- [x] 发布 COMPLETED 或 FAILED；
- [x] 保存到官方 Task Store。

### Client 子任务

- [x] 用 A2ACardResolver 发现 Agent Card；
- [x] 用 create_client() 创建官方 Client；
- [x] 构造用户 Message；
- [x] 消费 StreamResponse oneof；
- [x] 识别 task、status_update、artifact_update；
- [x] 用 GetTask 读取最终任务。

### 关键代码形状

    await event_queue.enqueue_event(
        new_task_from_user_message(context.message)
    )
    await updater.start_work(...)
    await updater.add_artifact(...)
    await updater.complete()

### 产物

- D:\MyLab\hi-agent\protocols\a2a\integration\server.py
- D:\MyLab\hi-agent\protocols\a2a\integration\client.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_a2a_sdk_integration.py
- D:\MyLab\hi-agent\docs\protocol-lab\experiments\a2a-sdk-integration.md
- D:\MyLab\hi-agent\docs\protocol-lab\reports\a2a-sdk-differential.md

### 完成标准

测试能证明：

    Agent Card discovery
      → SendStreamingMessage
      → Task
      → WORKING
      → Artifact
      → COMPLETED
      → GetTask

## 6. P2：Research Agent → Coding Agent 委托编排

这是下一阶段主线。不要先增加更多协议对象，而是让一次真实 Hi-Agent
请求决定“本地执行”还是“委托给远端 Coding Agent”。

### 6.1 委托决策

候选决策输入：

- 任务类型；
- 当前 Agent 是否拥有所需 skill；
- 远端 Agent Card 的 skill；
- 预计执行时间；
- 工具权限；
- 当前 Context token budget；
- 远端 Agent 的健康状态。

最小输出：

    LocalExecution
    DelegateToAgent(agent_name, skill_id, reason)
    Reject(reason)

### 待办

- [ ] 定义 DelegationRequest；
- [ ] 定义 DelegationDecision；
- [ ] 把 Agent Card skill 映射到高层目标；
- [ ] 不把 MCP tool name 直接当作 A2A skill；
- [ ] 记录 delegated_by、delegatee、skill_id 和 decision_reason；
- [ ] 为本地执行和远端委托各写一个对照测试；
- [ ] 测试远端 Agent Card 缺少匹配 skill 时 fail closed；
- [ ] 测试危险任务不能因为远端存在 skill 就绕过本地 Policy。

### 产物

- D:\MyLab\hi-agent\protocols\a2a\runtime\delegation.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_a2a_delegation.py
- D:\MyLab\hi-agent\docs\protocol-lab\decisions\a2a-delegation-decisions.md

### 完成标准

同一条用户请求可以被解释为：

    选择本地 MCP Tool
    或
    委托一个高层 A2A Task

两条路径都有清晰理由和 trace。

## 7. P3：远端 Task 观察和 Artifact 接收

### 目标

Research Agent 不应该只等待一个字符串。它需要建立远端 Task 的本地观察记录。

### 最小状态

    RemoteTaskObserved
      - remote_agent
      - remote_task_id
      - context_id
      - last_state
      - artifact_ids
      - started_at
      - finished_at
      - error_kind

### 待办

- [ ] 定义 RemoteTaskStore 接口；
- [ ] 记录远端 Agent Card 版本；
- [ ] 保存远端 task_id 和本地 correlation_id；
- [ ] 保存每个 Artifact 的 id、name、parts 摘要；
- [ ] stream 断开后可以用 GetTask 恢复；
- [ ] 防止重复 Artifact 导致重复消费；
- [ ] 设定 Artifact 大小和内容类型限制；
- [ ] 把 Artifact 转成 Hi-Agent ContextItem；
- [ ] 记录 provenance：哪个 Agent、哪个 Task、哪个工具产生了它；
- [ ] 测试 stream 中断、重复事件和最终 GetTask。

### 产物

- D:\MyLab\hi-agent\protocols\a2a\runtime\task_store.py
- D:\MyLab\hi-agent\protocols\a2a\runtime\artifact_bridge.py
- D:\MyLab\hi-agent\tests\protocol_lab\test_a2a_task_observation.py

### 完成标准

Research Agent 可以在 stream 中断后：

    correlation_id
      → remote task_id
      → GetTask
      → Artifact
      → ContextItem

## 8. P4：失败、超时、重试和取消

不能把所有远端失败都写成“Agent failed”。至少区分：

    card_resolution_error
    transport_error
    protocol_error
    remote_rejected
    remote_task_failed
    artifact_invalid
    timeout
    cancellation
    local_policy_denied

### 待办

- [ ] 统一 A2A RemoteError；
- [ ] 保存原始 SDK exception 类型和安全摘要；
- [ ] 给 SendMessage 设置 deadline；
- [ ] 设计只读任务的有限重试；
- [ ] 禁止非幂等委托自动重试；
- [ ] 设计 GetTask fallback；
- [ ] 设计 CancellationToken 到 Executor 的传递；
- [ ] 让 MCP Host 支持被 A2A 任务取消；
- [ ] 测试 stream 断开后不会重复执行危险操作；
- [ ] 测试失败 Artifact 不会被当成成功结果注入 Context。

### 完成标准

一次失败可以回答：

    失败发生在 discovery、transport、SDK protocol、
    remote executor、MCP policy、MCP tool 还是 Artifact bridge？

## 9. P5：身份、认证和多租户专题

这部分不进入第一条核心闭环，等 P2-P4 稳定后单独启动。

### 候选专题

- [ ] signed Agent Card / JWS；
- [ ] OAuth 2.0；
- [ ] PKCE；
- [ ] mTLS；
- [ ] tenant routing；
- [ ] per-tenant Task Store；
- [ ] credential forwarding policy；
- [ ] Agent Card skill-level security；
- [ ] 审计日志与敏感信息脱敏；
- [ ] 远端 Agent 供应链信任。

### 安全原则

- [ ] Agent Card 是声明，不是自动授权；
- [ ] 远端 skill 匹配不能绕过本地 Policy；
- [ ] 远端 Artifact 不能直接变成可执行 Tool；
- [ ] credential 不进入 Message、Artifact 或普通 trace；
- [ ] 不把完整远端上下文默认注入本地模型。

### 退出标准

完成一个可解释的认证闭环即可暂停，不追求一次覆盖全部 enterprise feature。

## 10. P6：A2A × MCP × Context 评测

真正值得比较的不是“能不能发消息”，而是委托是否改善了系统行为。

### 最小基线

1. 本地直接调用 MCP Tool；
2. 远端 A2A Coding Agent；
3. 远端 Agent 但不使用 Context Selector；
4. 远端 Agent 使用 MCP Host 和 Selector；
5. 远端 Artifact 注入 Context 前后对比。

### 指标

- task success；
- Artifact completeness；
- required evidence recall；
- remote failure recovery；
- end-to-end latency；
- A2A event count；
- MCP tool call count；
- prompt tokens；
- cached tokens；
- duplicate execution count；
- cost per successful task。

### 待办

- [ ] 建立固定的 repository repair / inspect cases；
- [ ] 测试本地执行与远端委托的正确率；
- [ ] 测试远端 Artifact 是否保留 MCP trace；
- [ ] 测试任务失败后的拒答质量；
- [ ] 测试 stream 与 polling 的延迟和恢复差异；
- [ ] 记录 SDK 版本、Agent Card、工具目录和 fixture hash；
- [ ] 形成一份可复现报告。

### 完成标准

能够用实验回答：

    什么类型的工作值得委托给 Agent？
    远端 Agent 带来的收益是否超过通信和状态管理成本？

## 11. 推荐的实际执行顺序

~~~text
P0  Mini-A2A 收口
 ↓
P1  官方 SDK Server / Client
 ↓
P2  Research → Coding 委托决策
 ↓
P3  Remote Task / Artifact observation
 ↓
P4  failure / timeout / cancellation
 ↓
P6  evaluation
 ↓
P5  security专题
~~~

不要因为认证听起来更“生产”就跳过 P2-P4。没有任务委托和恢复实验，
认证只会保护一个尚未定义清楚的工作流。

## 12. Definition of Done

### Core V1

- [x] Mini-A2A 五对象 contract；
- [x] Mini-A2A lifecycle tests；
- [x] 官方 A2A v1 Agent Card；
- [x] 官方 Server / Client；
- [x] streaming；
- [x] MCP Host bridge；
- [x] Artifact；
- [x] GetTask；
- [x] integration test；
- [x] 博客和实验记录。

### Delegation V1

- [ ] Research Agent 能基于 skill 委托 Coding Agent；
- [ ] 委托决策有理由；
- [ ] remote task 有本地 correlation_id；
- [ ] stream 断开可以 GetTask 恢复；
- [ ] Artifact 可以进入 Context；
- [ ] 失败类型可诊断；
- [ ] 任务不会重复执行危险操作；
- [ ] 有本地执行 vs 远端委托对照报告。

### Enterprise follow-up

- [ ] signed Agent Card；
- [ ] OAuth / PKCE；
- [ ] mTLS；
- [ ] push notification；
- [ ] multi-tenancy；
- [ ] gRPC；
- [ ] ANP discovery / DID / trust。

完成 Core V1 不等于 A2A 生产就绪，只代表已经拥有继续研究委托 runtime 的可靠夹具。

## 13. 给未来自己的提醒

MCP 和 A2A 的组合不是：

    Agent A 调用一个更大的 Tool

而是：

    Agent A 委托一个目标
    Agent B 自己规划并使用内部工具
    Agent B 发布状态和 Artifact
    Agent A 决定如何消费、验证或拒绝 Artifact

因此三条边界必须一直保持：

    AgentCard  != MCP tool catalog
    Task       != one-shot tool result
    Artifact   != “done” 字符串

如果一个新抽象不能帮助解释这三条边界，就先不要加。
