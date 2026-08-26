from __future__ import annotations

import asyncio

import httpx

from protocols.a2a.integration import (
    A2AResearchClient,
    build_coding_agent_app,
)
from protocols.a2a.mini_a2a import (
    AgentCard as MiniAgentCard,
    AgentSkill as MiniAgentSkill,
    Message as MiniMessage,
    MiniA2AClient,
    MiniA2AServer,
    Part as MiniPart,
    Role as MiniRole,
    StaticArtifactExecutor,
    Task as MiniTask,
    TaskState as MiniTaskState,
)
from protocols.mcp.host import MCPHost
from protocols.mcp.host.manager import MCPServerConfig
from tests.protocol_lab.test_mcp_host import make_server
from a2a.types import TaskState


def make_host() -> MCPHost:
    host = MCPHost()
    host.add_server(
        MCPServerConfig(
            server_id="filesystem",
            source=make_server(),
        )
    )
    return host


def test_official_card_discovery_hides_mcp_tool_inventory():
    host = make_host()

    async def scenario():
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
            assert client.agent_card.name == "hi-agent-coder"
            assert client.agent_card.skills[0].id == "repository-inspection"
            assert "grep_code" not in client.agent_card.skills[0].description


    asyncio.run(scenario())


def test_official_a2a_stream_bridges_mcp_to_artifact():
    host = make_host()

    async def scenario():
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
            assert kinds == [
                "task",
                "status_update",
                "artifact_update",
                "status_update",
            ]
            task = events[0].task
            assert task.status.state == TaskState.TASK_STATE_SUBMITTED
            assert (
                events[-1].status_update.status.state
                == TaskState.TASK_STATE_COMPLETED
            )
            assert events[2].artifact_update.artifact.name == (
                "repository-research"
            )
            assert events[2].artifact_update.last_chunk is True
            evidence = events[2].artifact_update.artifact.parts[0].data
            assert evidence.struct_value.fields["selected_tool"].string_value == (
                "filesystem.grep_code"
            )
            stored = await client.get_task(task.id)
            assert stored.id == task.id
            assert stored.artifacts[0].name == "repository-research"

    asyncio.run(scenario())


def test_mini_and_official_sdk_share_core_lifecycle_semantics():
    mini_server = MiniA2AServer(
        MiniAgentCard(
            name="mini-coder",
            description="teaching fixture",
            version="0.1.0",
            protocol_version="1.0",
            url="http://mini",
            skills=[
                MiniAgentSkill(
                    id="inspection",
                    name="Inspection",
                    description="inspect repositories",
                )
            ],
        ),
        StaticArtifactExecutor(),
    )
    mini_response = MiniA2AClient(mini_server).send_message(
        MiniMessage(
            message_id="mini-message",
            role=MiniRole.USER,
            parts=[MiniPart(text="Inspect the repository.")],
        )
    )
    assert isinstance(mini_response, MiniTask)
    mini_task = mini_server.process_task(mini_response.id)
    mini_semantics = [
        MiniTaskState.SUBMITTED.value,
        MiniTaskState.WORKING.value,
        "artifact",
        mini_task.status.state.value,
    ]

    host = make_host()

    async def scenario():
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
            official_semantics = [
                TaskState.Name(events[0].task.status.state)
                .removeprefix("TASK_STATE_")
                .lower(),
                TaskState.Name(events[1].status_update.status.state)
                .removeprefix("TASK_STATE_")
                .lower(),
                "artifact",
                TaskState.Name(events[-1].status_update.status.state)
                .removeprefix("TASK_STATE_")
                .lower(),
            ]
            assert [event.WhichOneof("payload") for event in events] == [
                "task",
                "status_update",
                "artifact_update",
                "status_update",
            ]
            assert official_semantics == [
                "submitted",
                "working",
                "artifact",
                "completed",
            ]

    asyncio.run(scenario())
    assert mini_semantics == [
        "submitted",
        "working",
        "artifact",
        "completed",
    ]
