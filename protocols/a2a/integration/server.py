"""Official A2A v1 Server adapter for the Hi-Agent Coding Agent."""

from __future__ import annotations

import asyncio
from typing import Any

from a2a.helpers import (
    new_data_part,
    new_task_from_user_message,
    new_text_message,
    new_text_part,
)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Role,
)
from starlette.applications import Starlette


def build_coding_agent_card(
    base_url: str = "http://127.0.0.1:9001",
) -> AgentCard:
    """构造官方 proto-based Agent Card。

    A2A v1 的 Agent Card 对外描述 Agent 的高层能力和通信 interface；
    这里不会把 MCP Host 的 grep_code、read_file 等内部实现泄露给发现者。
    """

    base_url = base_url.rstrip("/")
    return AgentCard(
        name="hi-agent-coder",
        description="Inspects repositories through Hi-Agent MCP Host.",
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                protocol_version="1.0",
                url=f"{base_url}/a2a/jsonrpc",
            )
        ],
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        skills=[
            AgentSkill(
                id="repository-inspection",
                name="Repository Inspection",
                description=(
                    "Inspect repository code and return an evidence artifact."
                ),
                tags=["repository", "coding", "inspection"],
                input_modes=["text/plain"],
                output_modes=["text/plain", "application/json"],
                examples=[
                    "Inspect the repository and report selector code.",
                ],
            )
        ],
    )


class MCPBackedA2AExecutor(AgentExecutor):
    """把官方 A2A Task 执行桥接到现有 MCP Host。

    官方 SDK 的 Executor 只负责向 EventQueue 发布标准 A2A 事件。工具选择、
    policy、调用和 trace 仍然由 Hi-Agent MCPHost 负责，避免两个协议层互相
    复制实现。
    """

    def __init__(self, mcp_host: Any) -> None:
        self.mcp_host = mcp_host

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """实现 SDK 要求的 cancel hook。

        本实验还没有把真实 MCP 调用做成可取消的后台 job，因此这里先把
        cancel 事件交给官方 TaskUpdater；下一阶段再把取消 token 贯穿到
        MCP Host 和长任务执行器。
        """

        if context.task_id and context.context_id:
            updater = TaskUpdater(
                event_queue=event_queue,
                task_id=context.task_id,
                context_id=context.context_id,
            )
            await updater.cancel()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """执行一次长任务，严格使用 Task-first streaming mode。"""

        message = context.message
        task_id = context.task_id
        context_id = context.context_id
        if message is None or not task_id or not context_id:
            return

        query = context.get_user_input()
        if self._is_capability_question(query):
            await event_queue.enqueue_event(
                new_text_message(
                    "I inspect repositories through MCP and return artifacts.",
                    context_id=context_id,
                    role=Role.ROLE_AGENT,
                )
            )
            return

        # 第一条事件必须是 Task。官方 SDK 会据此判断进入 task stream，
        # 后续只允许 status/artifact update，不能再混入 Message。
        await event_queue.enqueue_event(new_task_from_user_message(message))
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task_id,
            context_id=context_id,
        )
        await updater.start_work(
            message=updater.new_agent_message(
                parts=[new_text_part("Coding Agent is selecting MCP tools.")]
            )
        )

        try:
            selection = await asyncio.to_thread(
                self.mcp_host.select_tools,
                query,
            )
            if not selection.selected:
                raise RuntimeError("no relevant MCP tool selected")

            entry = next(
                (
                    candidate
                    for candidate in selection.selected
                    if candidate.original_tool_name == "grep_code"
                ),
                selection.selected[0],
            )
            execution = await asyncio.to_thread(
                self.mcp_host.execute,
                entry.canonical_tool_name,
                {"query": query},
                selected_by="official_a2a_coding_executor",
                selection_reason=selection.reasons[
                    entry.canonical_tool_name
                ],
            )
            evidence = {
                "selected_tool": entry.canonical_tool_name,
                "result": execution.result,
                "trace": execution.trace.as_dict(),
            }
            await updater.add_artifact(
                parts=[
                    new_data_part(evidence),
                    new_text_part(
                        "Coding Agent completed an MCP-backed inspection."
                    ),
                ],
                name="repository-research",
                last_chunk=True,
            )
            await updater.complete()
        except Exception as exc:
            await updater.failed(
                message=updater.new_agent_message(
                    parts=[new_text_part(f"task failed: {exc}")]
                )
            )

    @staticmethod
    def _is_capability_question(query: str) -> bool:
        lowered = query.lower()
        return any(
            marker in lowered
            for marker in (
                "what can you do",
                "what do you support",
                "你支持什么",
            )
        )


def build_coding_agent_app(
    mcp_host: Any,
    *,
    base_url: str = "http://127.0.0.1:9001",
) -> tuple[Starlette, AgentCard]:
    """组装官方 A2A v1 JSON-RPC + Agent Card ASGI app。

    route factory 是 SDK 1.x 的公开组装方式。这里不引入 FastAPI 或 gRPC，
    因为当前实验的目标是先证明 Agent Card、SendStreamingMessage、Task、
    Artifact 和 GetTask 的组合 contract。
    """

    card = build_coding_agent_card(base_url)
    request_handler = DefaultRequestHandler(
        agent_executor=MCPBackedA2AExecutor(mcp_host),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(
            request_handler=request_handler,
            rpc_url="/a2a/jsonrpc",
        ),
    ]
    app = Starlette(routes=routes)
    app.state.a2a_request_handler = request_handler
    return app, card
