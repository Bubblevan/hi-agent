from __future__ import annotations

import pytest

from protocols.a2a_lab import (
    AgentCard,
    AgentSkill,
    Message,
    MiniA2AServer,
    Part,
    Role,
    StaticArtifactExecutor,
    Task,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    validate_stream,
)


def make_server():
    return MiniA2AServer(
        AgentCard(
            name="coder",
            description="coding agent",
            version="0.1.0",
            protocol_version="1.0",
            url="http://localhost:9001",
            skills=[
                AgentSkill(
                    id="coding",
                    name="Coding",
                    description="inspect and test code",
                )
            ],
        ),
        StaticArtifactExecutor(),
    )


def test_task_stream_has_submitted_working_artifact_completed():
    events = list(
        make_server().send_message_stream(
            Message(
                message_id="message-stream",
                role=Role.USER,
                parts=[Part(text="inspect repository")],
            )
        )
    )

    assert isinstance(events[0], Task)
    assert events[0].status.state is TaskState.SUBMITTED
    assert isinstance(events[1], TaskStatusUpdateEvent)
    assert events[1].status.state is TaskState.WORKING
    assert any(isinstance(event, TaskArtifactUpdateEvent) for event in events)
    assert isinstance(events[-1], TaskStatusUpdateEvent)
    assert events[-1].final is True
    assert events[-1].status.state is TaskState.COMPLETED
    assert validate_stream(events) == "task"


def test_message_stream_contains_only_one_message():
    server = make_server()
    events = list(
        server.send_message_stream(
            Message(
                message_id="message-help",
                role=Role.USER,
                parts=[Part(text="What can you do?")],
            )
        )
    )

    assert len(events) == 1
    assert isinstance(events[0], Message)
    assert validate_stream(events) == "message"


def test_message_and_task_stream_modes_cannot_mix():
    with pytest.raises(ValueError):
        validate_stream(
            [
                Message(
                    message_id="message-1",
                    role=Role.AGENT,
                    parts=[Part(text="hello")],
                ),
                Task(
                    id="task-1",
                    context_id="context-1",
                    status=TaskStatus(TaskState.SUBMITTED),
                ),
            ]
        )


def test_completed_task_stream_requires_artifact():
    with pytest.raises(ValueError):
        validate_stream(
            [
                Task(
                    id="task-1",
                    context_id="context-1",
                    status=TaskStatus(TaskState.SUBMITTED),
                ),
                TaskStatusUpdateEvent(
                    task_id="task-1",
                    status=TaskStatus(TaskState.WORKING),
                ),
                TaskStatusUpdateEvent(
                    task_id="task-1",
                    status=TaskStatus(TaskState.COMPLETED),
                    final=True,
                ),
            ]
        )
