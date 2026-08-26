from __future__ import annotations

from protocols.a2a.mini_a2a import (
    AgentCard,
    AgentSkill,
    CodingAgentExecutor,
    Message,
    MiniA2AClient,
    MiniA2AServer,
    Part,
    Role,
    Task,
    TaskState,
)
from protocols.mcp.host import MCPHost
from protocols.mcp.host.manager import MCPServerConfig
from tests.protocol_lab.test_mcp_host import make_server


def test_coding_agent_delegates_to_mcp_host_and_returns_artifact():
    host = MCPHost()
    host.add_server(
        MCPServerConfig(
            server_id="filesystem",
            source=make_server(),
        )
    )
    server = MiniA2AServer(
        AgentCard(
            name="hi-agent-coder",
            description="A coding agent backed by MCP tools.",
            version="0.1.0",
            protocol_version="1.0",
            url="http://localhost:9001",
            skills=[
                AgentSkill(
                    id="repository-inspection",
                    name="Repository Inspection",
                    description="Inspect source code and return an artifact.",
                )
            ],
        ),
        CodingAgentExecutor(host),
    )
    client = MiniA2AClient(server)

    response = client.send_message(
        Message(
            message_id="message-bridge",
            role=Role.USER,
            parts=[
                Part(
                    text=(
                        "Inspect the repository code and report the "
                        "Mini-MCP protocol files."
                    )
                )
            ],
        )
    )
    assert isinstance(response, Task)
    completed = server.process_task(response.id)

    assert completed.status.state is TaskState.COMPLETED
    artifact = completed.artifacts[0]
    evidence = artifact.parts[0].data
    assert evidence["selected_tool"] == "filesystem.grep_code"
    assert evidence["trace"]["status"] == "completed"
    assert evidence["trace"]["selected_by"] == "a2a_coding_executor"
