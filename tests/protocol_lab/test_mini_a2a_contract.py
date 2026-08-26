from __future__ import annotations

from protocols.a2a.mini_a2a import (
    AgentCard,
    AgentSkill,
    Artifact,
    Message,
    MiniA2AClient,
    MiniA2AServer,
    Part,
    Role,
    StaticArtifactExecutor,
    Task,
    TaskState,
)


def make_server():
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
    return MiniA2AServer(card, StaticArtifactExecutor())


def test_agent_card_is_agent_capability_not_mcp_tool_inventory():
    card = MiniA2AClient(make_server()).get_agent_card()

    assert card.name == "hi-agent-coder"
    assert card.skills[0].id == "repository-inspection"
    assert "grep_code" not in card.skills[0].description


def test_immediate_message_response_does_not_create_task():
    client = MiniA2AClient(make_server())

    response = client.send_message(
        Message(
            message_id="message-capabilities",
            role=Role.USER,
            parts=[Part(text="What can you do?")],
        )
    )

    assert isinstance(response, Message)
    assert response.role is Role.AGENT
    assert response.task_id is None


def test_long_request_returns_submitted_task():
    client = MiniA2AClient(make_server())

    response = client.send_message(
        Message(
            message_id="message-repair",
            role=Role.USER,
            parts=[Part(text="Inspect this repository and prepare a report.")],
        )
    )

    assert isinstance(response, Task)
    assert response.status.state is TaskState.SUBMITTED
    assert response.history[0].message_id == "message-repair"
    assert response.artifacts == []


def test_message_and_artifact_parts_support_text_and_data():
    text_message = Message(
        message_id="message-1",
        role=Role.USER,
        parts=[Part(text="hello")],
    )
    artifact = Artifact(
        artifact_id="artifact-1",
        name="report",
        description="structured report",
        parts=[Part(data={"passed": 3}), Part(text="all good")],
    )

    assert text_message.text == "hello"
    assert artifact.parts[0].data == {"passed": 3}
