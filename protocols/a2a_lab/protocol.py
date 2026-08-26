"""Mini-A2A operations and the task lifecycle contract."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import uuid4

from .models import (
    AgentCard,
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)


class InvalidTaskTransition(ValueError):
    """Raised when a Task attempts an illegal state transition."""


_ALLOWED_TRANSITIONS = {
    TaskState.SUBMITTED: {TaskState.WORKING, TaskState.FAILED},
    TaskState.WORKING: {TaskState.COMPLETED, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: set(),
}


def transition_task(
    task: Task,
    new_state: TaskState,
    *,
    message: Message | None = None,
) -> Task:
    allowed = _ALLOWED_TRANSITIONS[task.status.state]
    if new_state not in allowed:
        raise InvalidTaskTransition(
            f"{task.status.state.value} -> {new_state.value}"
        )
    task.status = TaskStatus(new_state, message)
    if message is not None:
        task.history.append(message)
    return task


@dataclass(frozen=True, slots=True)
class TaskStatusUpdateEvent:
    task_id: str
    status: TaskStatus
    final: bool = False


@dataclass(frozen=True, slots=True)
class TaskArtifactUpdateEvent:
    task_id: str
    artifact: Artifact


class MiniA2AServer:
    """A local server implementing only the five-object teaching contract."""

    def __init__(
        self,
        card: AgentCard,
        executor: Any,
    ) -> None:
        self.card = card
        self.executor = executor
        self._tasks: dict[str, Task] = {}

    def get_agent_card(self) -> AgentCard:
        return self.card

    def send_message(self, message: Message) -> Message | Task:
        if not isinstance(message, Message):
            raise TypeError("send_message requires Message")

        # Immediate capability questions demonstrate that Message and Task
        # are distinct response shapes.
        if message.text and any(
            marker in message.text.lower()
            for marker in ("what can you do", "what do you support", "你支持什么")
        ):
            return Message(
                message_id=f"message-{uuid4().hex}",
                role=Role.AGENT,
                parts=[
                    Part(
                        text=(
                            "I can inspect repositories, run tests, "
                            "and return an Artifact."
                        )
                    )
                ],
                context_id=message.context_id,
            )

        task = Task(
            id=f"task-{uuid4().hex}",
            context_id=message.context_id or f"context-{uuid4().hex}",
            status=TaskStatus(TaskState.SUBMITTED),
            history=[message],
        )
        self._tasks[task.id] = task
        return task

    def get_task(self, task_id: str) -> Task:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown task: {task_id}") from exc

    def process_task(self, task_id: str) -> Task:
        task = self.get_task(task_id)
        transition_task(task, TaskState.WORKING)
        try:
            artifact = self.executor.execute(task.history[0], task)
            if not isinstance(artifact, Artifact):
                raise TypeError("executor must return Artifact")
            task.artifacts.append(artifact)
            transition_task(task, TaskState.COMPLETED)
        except Exception as exc:
            failure = Message(
                message_id=f"message-{uuid4().hex}",
                role=Role.AGENT,
                parts=[Part(text=f"task failed: {exc}")],
                task_id=task.id,
                context_id=task.context_id,
            )
            transition_task(
                task,
                TaskState.FAILED,
                message=failure,
            )
        return task

    def send_message_stream(
        self,
        message: Message,
    ):
        response = self.send_message(message)
        if isinstance(response, Message):
            events: list[Any] = [response]
            validate_stream(events)
            yield response
            return

        # Yield a snapshot so the SUBMITTED event does not mutate into
        # COMPLETED when the same Task object is updated later.
        yield deepcopy(response)
        transition_task(response, TaskState.WORKING)
        yield TaskStatusUpdateEvent(
            task_id=response.id,
            status=response.status,
        )
        try:
            artifact = self.executor.execute(response.history[0], response)
            if not isinstance(artifact, Artifact):
                raise TypeError("executor must return Artifact")
            response.artifacts.append(artifact)
            yield TaskArtifactUpdateEvent(
                task_id=response.id,
                artifact=artifact,
            )
            transition_task(response, TaskState.COMPLETED)
            yield TaskStatusUpdateEvent(
                task_id=response.id,
                status=response.status,
                final=True,
            )
        except Exception as exc:
            failure = Message(
                message_id=f"message-{uuid4().hex}",
                role=Role.AGENT,
                parts=[Part(text=f"task failed: {exc}")],
                task_id=response.id,
                context_id=response.context_id,
            )
            transition_task(
                response,
                TaskState.FAILED,
                message=failure,
            )
            yield TaskStatusUpdateEvent(
                task_id=response.id,
                status=response.status,
                final=True,
            )
        self._tasks[response.id] = response


def validate_stream(events: Iterable[Any]) -> str:
    """Reject Message/Task stream mixing and invalid terminal ordering."""

    events = list(events)
    if not events:
        raise ValueError("stream must not be empty")
    if isinstance(events[0], Message):
        if len(events) != 1 or not all(
            isinstance(event, Message) for event in events
        ):
            raise ValueError("Message mode must contain exactly one Message")
        return "message"

    if not isinstance(events[0], Task):
        raise ValueError("Task mode must start with Task")
    if events[0].status.state is not TaskState.SUBMITTED:
        raise ValueError("Task stream must start with SUBMITTED")

    seen_artifact = False
    final_seen = False
    for event in events[1:]:
        if isinstance(event, Message):
            raise ValueError("Message and Task stream modes cannot be mixed")
        if isinstance(event, TaskArtifactUpdateEvent):
            if event.task_id != events[0].id:
                raise ValueError("stream event task_id does not match Task")
            if final_seen:
                raise ValueError("cannot update a terminal Task")
            seen_artifact = True
            continue
        if not isinstance(event, TaskStatusUpdateEvent):
            raise ValueError(f"unsupported stream event: {type(event)!r}")
        if event.task_id != events[0].id:
            raise ValueError("stream event task_id does not match Task")
        if final_seen:
            raise ValueError("cannot update a terminal Task")
        if event.final:
            if event.status.state not in {
                TaskState.COMPLETED,
                TaskState.FAILED,
            }:
                raise ValueError("final status must be terminal")
            if event.status.state is TaskState.COMPLETED and not seen_artifact:
                raise ValueError("completed Task stream must contain Artifact")
            final_seen = True
    if not final_seen:
        raise ValueError("Task stream must finish with final status")
    return "task"
