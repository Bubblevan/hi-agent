# Mini-A2A V1 实验记录

日期：2026-08-26

## 学习问题

为什么 Coding Agent 不能简单地被包装成一个 MCP Tool？

MCP 的最小单元是：

    call_tool("grep_code", arguments)
      → result

Mini-A2A 的最小单元是：

    SendMessage
      → Task(SUBMITTED)
      → Task(WORKING)
      → Artifact
      → Task(COMPLETED)

工具调用强调一次能力执行，Task 强调一个可以持续、失败、汇报状态并交付成果
的工作单元。

## 本轮 contract

只实现五个核心对象：

- AgentCard；
- Message；
- Task；
- TaskStatus；
- Artifact。

Part 只支持 text 和 data。Task 只支持 SUBMITTED、WORKING、COMPLETED、FAILED。

只实现三个操作：

    get_agent_card()
    send_message(message)
    get_task(task_id)

另加一个本地 stream 实验，不做 HTTP、认证、push notification 或 gRPC。

## 实际代码

    card = AgentCard(
        name="hi-agent-coder",
        description="Inspects repositories and returns evidence.",
        version="0.1.0",
        protocol_version="1.0",
        url="http://localhost:9001",
        skills=[
            AgentSkill(
                id="repository-inspection",
                name="Repository Inspection",
                description="Inspect code and return a structured artifact.",
            )
        ],
    )

    server = MiniA2AServer(
        card,
        CodingAgentExecutor(mcp_host),
    )

    response = server.send_message(
        Message(
            message_id="message-bridge",
            role=Role.USER,
            parts=[Part(text="Inspect the repository code.")],
        )
    )

    task = server.process_task(response.id)

## 生命周期观察

    >>> response.status.state
    <TaskState.SUBMITTED: 'submitted'>

    >>> task.status.state
    <TaskState.COMPLETED: 'completed'>

    >>> task.artifacts[0].name
    'repository-research'

    >>> task.artifacts[0].parts[0].data["selected_tool"]
    'filesystem.grep_code'

Task 的状态转换由 protocol.py 统一校验。COMPLETED 之后再次进入 WORKING 会抛出：

    InvalidTaskTransition: completed -> working

这条失败路径比多写几个“Agent 调用成功”的 demo 更能说明 Task 的价值。

## Message response 和 Task response

能力咨询可以立即返回 Message：

    What can you do?
      → Message(role=agent)

仓库检查则返回 Task：

    Inspect this repository and prepare a report.
      → Task(SUBMITTED)

这说明 A2A 并不是“所有消息都包成 Task”。短回答和长期工作需要不同的响应形状。

## Stream 输出

Task stream 的教学输出：

    Task(status=SUBMITTED)
    TaskStatusUpdateEvent(status=WORKING, final=False)
    TaskArtifactUpdateEvent(artifact=repository-research)
    TaskStatusUpdateEvent(status=COMPLETED, final=True)

Message stream 则只能包含一个 Message。Mini-A2A 会拒绝 Message 和 Task 事件混用，
也会拒绝没有 Artifact 就宣称 COMPLETED。

## 和 MCP Host 的组合

CodingAgentExecutor 不把 MCP wire 协议塞进 A2A Server：

    A2A Server
      → CodingAgentExecutor
      → MCPHost.select_tools()
      → MCPHost.execute()
      → MCPCallResult + MCPTrace
      → Artifact

Artifact 里保存的是交付证据，而不只是 done：

    {
        "selected_tool": "filesystem.grep_code",
        "result": "{\"result\": [\"mini_mcp/protocol.py\"]}",
        "trace": {
            "status": "completed",
            "selected_by": "a2a_coding_executor"
        }
    }

## 协议八卦

很多 Agent demo 把“Agent 返回一段字符串”直接当成协作完成。A2A 真正有意思的
地方恰恰是把 Message、Task 和 Artifact 分开：消息可以很多轮，Task 可以中途
失败，Artifact 可以独立被消费或审计。

另一个容易混淆的地方是 AgentCard。它应该描述“这个 Agent 对外能完成什么目标”，
而不是把内部 MCP 工具清单泄漏出去。Coding Agent 对外可以声明 repository-inspection，
内部再选择 grep_code、read_file 或 pytest。

## 本轮边界

暂不实现：

    input-required
    auth-required
    canceled
    rejected
    CancelTask
    ListTasks
    push notification
    OAuth / mTLS / JWS
    HTTP+JSON / gRPC

下一步才是把 Mini-A2A 的五对象 contract 与官方 A2A SDK 做差分，再接入真实
Research Agent → Coding Agent 的委托链。

