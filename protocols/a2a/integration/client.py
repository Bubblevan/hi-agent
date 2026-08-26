"""Official A2A v1 Client adapter used by the Research Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from a2a.client import A2ACardResolver, Client, ClientConfig, create_client
from a2a.helpers import new_text_message
from a2a.types import (
    AgentCard,
    GetTaskRequest,
    Message,
    Role,
    SendMessageRequest,
    StreamResponse,
    Task,
)


def build_user_message(
    text: str,
    *,
    context_id: str | None = None,
) -> Message:
    """构造官方 v1 Message，而不是 Mini-A2A dataclass。"""

    return new_text_message(
        text,
        context_id=context_id,
        role=Role.ROLE_USER,
    )


@dataclass(slots=True)
class A2AResearchClient:
    """Research Agent 侧的最小官方 SDK adapter。

    connect() 先通过 /.well-known/agent-card.json 做 discovery，再让 SDK
    根据 Card 选择 JSON-RPC interface。调用方只看到 A2A Message/Task/stream，
    不需要知道底层 HTTP 请求的拼装细节。
    """

    client: Client
    agent_card: AgentCard

    @classmethod
    async def connect(
        cls,
        base_url: str,
        *,
        httpx_client: Any | None = None,
    ) -> "A2AResearchClient":
        if httpx_client is None:
            httpx_client = _new_httpx_client()
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url.rstrip("/"),
        )
        card = await resolver.get_agent_card()
        client = await create_client(
            card,
            client_config=ClientConfig(
                streaming=True,
                httpx_client=httpx_client,
            ),
        )
        return cls(client=client, agent_card=card)

    async def send_message(self, text: str) -> list[StreamResponse]:
        """通过官方 SendStreamingMessage 获取完整事件列表。"""

        request = SendMessageRequest(
            message=build_user_message(text),
        )
        return [
            event async for event in self.client.send_message(request)
        ]

    async def get_task(self, task_id: str) -> Task:
        """通过官方 GetTask 读取 Task Store 中的最终状态。"""

        return await self.client.get_task(GetTaskRequest(id=task_id))

    async def close(self) -> None:
        await self.client.close()


def _new_httpx_client() -> Any:
    import httpx

    return httpx.AsyncClient()
