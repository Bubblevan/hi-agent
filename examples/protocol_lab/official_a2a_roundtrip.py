"""Run one official A2A v1 roundtrip against an in-process MCP Host."""

from __future__ import annotations

import asyncio

import httpx
from mcp.server import MCPServer

from protocols.a2a.integration import A2AResearchClient, build_coding_agent_app
from protocols.mcp.host import MCPHost
from protocols.mcp.host.manager import MCPServerConfig
from a2a.types import TaskState


def build_mcp_host() -> MCPHost:
    server = MCPServer(name="local-files", version="1.0.0")

    def grep_code(query: str) -> list[str]:
        return [f"protocols/mcp/mini_mcp/{query}.py"]

    server.tool()(grep_code)
    host = MCPHost()
    host.add_server(
        MCPServerConfig(
            server_id="filesystem",
            source=server,
        )
    )
    return host


async def main(host: MCPHost) -> None:
    app, _ = build_coding_agent_app(
        host,
        base_url="http://testserver",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as http_client:
        client = await A2AResearchClient.connect(
            "http://testserver",
            httpx_client=http_client,
        )
        events = await client.send_message(
            "Inspect the repository code and report Mini-MCP files.",
        )
        kinds = [event.WhichOneof("payload") for event in events]
        artifact_event = next(
            event for event in events if event.HasField("artifact_update")
        )
        task = events[0].task
        stored = await client.get_task(task.id)
        evidence = artifact_event.artifact_update.artifact.parts[0].data
        print(f"[card] {client.agent_card.name}")
        print(f"[events] {' -> '.join(kinds)}")
        print(
            "[artifact] "
            f"{artifact_event.artifact_update.artifact.name}"
        )
        print(
            "[selected_tool] "
            f"{evidence.struct_value.fields['selected_tool'].string_value}"
        )
        state = TaskState.Name(stored.status.state)
        print(f"[task] {state.removeprefix('TASK_STATE_').lower()}")


if __name__ == "__main__":
    asyncio.run(main(build_mcp_host()))
