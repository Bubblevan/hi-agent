from __future__ import annotations

import pytest

from protocols.a2a.mini_a2a import (
    AgentCard,
    AgentSkill,
    InvalidTaskTransition,
    Message,
    MiniA2AClient,
    MiniA2AServer,
    Part,
    Role,
    StaticArtifactExecutor,
    Task,
    TaskState,
    TaskStatus,
    transition_task,
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


def make_task() -> Task:
    return Task(
        id="task-1",
        context_id="context-1",
        status=TaskStatus(TaskState.SUBMITTED),
        history=[
            Message(
                message_id="message-1",
                role=Role.USER,
                parts=[Part(text="inspect repository")],
            )
        ],
    )


def test_task_lifecycle_submitted_working_artifact_completed():
    server = make_server()
    client = MiniA2AClient(server)
    submitted = client.send_message(
        Message(
            message_id="message-2",
            role=Role.USER,
            parts=[Part(text="inspect repository")],
        )
    )

    assert isinstance(submitted, Task)
    completed = server.process_task(submitted.id)

    assert completed.status.state is TaskState.COMPLETED
    assert len(completed.artifacts) == 1
    assert completed.artifacts[0].name == "result"
    assert client.get_task(submitted.id) is completed


def test_terminal_task_cannot_return_to_working():
    task = make_task()
    transition_task(task, TaskState.WORKING)
    transition_task(task, TaskState.COMPLETED)

    with pytest.raises(InvalidTaskTransition):
        transition_task(task, TaskState.WORKING)


def test_failed_executor_reaches_failed_terminal_state():
    class FailingExecutor(StaticArtifactExecutor):
        def execute(self, message, task):
            raise RuntimeError("compile failed")

    server = MiniA2AServer(
        make_server().get_agent_card(),
        FailingExecutor(),
    )
    submitted = server.send_message(
        Message(
            message_id="message-fail",
            role=Role.USER,
            parts=[Part(text="run the failing job")],
        )
    )

    task = server.process_task(submitted.id)

    assert task.status.state is TaskState.FAILED
    assert task.status.message is not None
    assert "compile failed" in task.status.message.text
