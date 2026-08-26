# Official A2A SDK 集成实验

日期：2026-08-26

## 实验问题

Mini-A2A 已经解释了 AgentCard、Message、Task、Artifact 和状态机。现在要验证：

    这些语义能不能落到真实 A2A v1 SDK 的
    Agent Card、JSON-RPC、EventQueue、Task Store 和 Client？

答案是可以，但应用层的边界发生了变化：

    Mini-A2A
        同步对象 + 本地 stream

    official a2a-sdk
        proto types + async EventQueue + route factory + Task Store

## 目录职责

    protocols/a2a/mini_a2a/
        学习夹具：帮助理解对象和状态机

    protocols/a2a/integration/
        工程集成：使用官方 a2a-sdk，把 Coding Agent 接入 MCP Host

这两个目录不能合并。合并后最容易产生的误解是“Mini-A2A 就是生产 SDK”。

## Server 侧最小代码

官方 Executor 的关键不是 return 一个 Artifact，而是把事件写入 EventQueue：

    class MCPBackedA2AExecutor(AgentExecutor):
        async def execute(self, context, event_queue):
            await event_queue.enqueue_event(
                new_task_from_user_message(context.message)
            )
            updater = TaskUpdater(
                event_queue=event_queue,
                task_id=context.task_id,
                context_id=context.context_id,
            )
            await updater.start_work(...)
            execution = await asyncio.to_thread(
                self.mcp_host.execute,
                "filesystem.grep_code",
                {"query": context.get_user_input()},
            )
            await updater.add_artifact(...)
            await updater.complete()

为什么使用 asyncio.to_thread？Hi-Agent 现有 MCP Host 为了兼容 MyTool 接口提供了同步
桥接；官方 A2A Executor 正处在 event loop 中，不能直接调用会再次 asyncio.run()
的同步 Manager。把同步 MCP 调用放到线程，是当前学习切片中最清楚的边界。

## Client 侧最小代码

    resolver = A2ACardResolver(httpx_client, "http://testserver")
    card = await resolver.get_agent_card()
    client = await create_client(
        card,
        client_config=ClientConfig(
            streaming=True,
            httpx_client=httpx_client,
        ),
    )

    request = SendMessageRequest(
        message=new_text_message(
            "Inspect the repository code.",
            role=Role.ROLE_USER,
        )
    )
    events = [event async for event in client.send_message(request)]

Client 先读 Agent Card，再根据 supported_interfaces 选择 JSON-RPC interface。
这个顺序比把 endpoint 写死在业务代码里更接近真实 Agent interoperability。

## 终端结果

    .venv\Scripts\python.exe -m pytest tests\protocol_lab\test_a2a_sdk_integration.py -q
    ..                                                               [100%]

事件 oneof 顺序：

    task
    status_update
    artifact_update
    status_update

状态顺序：

    TASK_STATE_SUBMITTED
    TASK_STATE_WORKING
    TASK_STATE_COMPLETED

Artifact 中可以读到：

    selected_tool = filesystem.grep_code
    trace.selected_by = official_a2a_coding_executor
    trace.status = completed

## 协议八卦

A2A v1 SDK 把一个 stream event 包成 StreamResponse，并用 oneof 区分 task、
message、status_update 和 artifact_update。它看起来比 Mini-A2A 的四个 Python
事件类更啰嗦，但这份啰嗦是有价值的：序列化边界被固定了，消费者不会靠猜对象
类型来解释远端事件。

另一个变化是 SDK 1.x 的 Server 组装方式。旧教程常见的 Application wrapper
在当前 SDK 路线上已经被 route factory 取代：Agent Card route 和 JSON-RPC route
直接挂进 Starlette/FastAPI。教程代码如果仍然复制旧 wrapper，通常不是概念错，
而是版本错。

还有一个很像“实现细节”的事实：A2A 的 Task Store 默认可以是
InMemoryTaskStore，但这并不意味着 Task 本身不需要持久化语义。远端调用者会在
第一次 stream 结束后用 GetTask 读取结果；真实部署只需要把 Store 换成数据库，
而不用改变 AgentCard、Message、Artifact 的上层 contract。

## 当前差异和停止线

Mini-A2A 保留四状态和同步 API，便于教学；官方 SDK 使用 proto enum、更多状态、
异步事件和可替换 Task Store。这是有意的分层，不是需要继续抹平的 bug。

本阶段已经满足：

    Agent Card discovery
    official A2A v1 Server
    official A2A v1 Client
    streaming Task lifecycle
    MCP Host bridge
    Artifact + GetTask

下一步转向真实的 Research Agent → Coding Agent 委托编排，新增观察字段：

    delegated_by
    task_id
    artifact_id
    remote_error

本轮不继续补齐 OAuth、mTLS、signed Agent Card、push notification、gRPC 或
multi-tenancy；它们应该作为独立专题。
