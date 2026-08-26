"""Mini-A2A 操作、生命周期和流式事件 contract。

本模块刻意把“协议行为”与“Agent 如何完成工作”分开：

    MiniA2AServer -> 接收 Message、维护 Task、发布事件
    AgentExecutor -> 决定如何检查仓库、调用 MCP、生成 Artifact

这种边界让我们可以用 StaticArtifactExecutor 测试协议本身，也可以用
CodingAgentExecutor 测试 A2A 到 MCP Host 的组合。
"""

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
    """Task 试图进行非法状态转换时抛出。"""


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
    """执行一次受约束的状态转换。

    状态机不是装饰性字段。它告诉调用方工作是否已经开始、是否仍可能
    继续、以及结果是否已经稳定。尤其是 COMPLETED/FAILED 是 terminal
    state，进入后不能“复活”。

    Mini contract 还把一个业务不变量放在这里集中检查：
    COMPLETED 必须已经拥有至少一个 Artifact。这样即使外部代码直接调用
    transition_task，也不能制造“完成但没有交付物”的伪成功。
    """

    allowed = _ALLOWED_TRANSITIONS[task.status.state]
    if new_state not in allowed:
        raise InvalidTaskTransition(
            f"{task.status.state.value} -> {new_state.value}"
        )
    if new_state is TaskState.COMPLETED and not task.artifacts:
        raise InvalidTaskTransition(
            "COMPLETED task must contain at least one Artifact"
        )
    task.status = TaskStatus(new_state, message)
    if message is not None:
        task.history.append(message)
    return task


@dataclass(frozen=True, slots=True)
class TaskStatusUpdateEvent:
    """流式任务状态快照。"""

    task_id: str
    status: TaskStatus
    final: bool = False


@dataclass(frozen=True, slots=True)
class TaskArtifactUpdateEvent:
    """流式发送一个新的 Task 交付物。"""

    task_id: str
    artifact: Artifact


class MiniA2AServer:
    """只实现五对象学习 contract 的进程内 A2A Server。

    这里的 Server 不是 HTTP 服务，也没有假装覆盖官方 A2A binding。它只
    提供可观察的核心语义，便于先理解 AgentCard、Task 和 Artifact 如何
    协作，再把同一个 AgentExecutor 接到官方 SDK。
    """

    def __init__(
        self,
        card: AgentCard,
        executor: Any,
    ) -> None:
        self.card = card
        self.executor = executor
        self._tasks: dict[str, Task] = {}

    def get_agent_card(self) -> AgentCard:
        """返回 discovery 名片。"""
        return self.card

    def send_message(self, message: Message) -> Message | Task:
        """接收一条消息，并决定即时回复还是创建长期 Task。

        这是 A2A 与 MCP 最重要的分叉之一：MCP tools/call 通常表达一次
        能力调用；A2A SendMessage 可以把一个目标委托给另一个 Agent，让
        对方自行规划，因而返回 Message 或 Task。
        """

        if not isinstance(message, Message):
            raise TypeError("send_message requires Message")

        # 即时能力问题用 Message 回复，证明 Message 与 Task 是两种不同的
        # response shape，而不是所有请求都强行创建 Task。
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
        """按 id 读取本地 Task；真实部署通常需要持久化 Task Store。"""
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise KeyError(f"unknown task: {task_id}") from exc

    def process_task(self, task_id: str) -> Task:
        """同步推进一次 Task：SUBMITTED -> WORKING -> 终态。

        Executor 只负责产出 Artifact；状态转换、失败消息和任务存储由
        Server 负责。这是协议层与应用层的最小分工。
        """

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
        """发布 Message 模式或 Task 模式的事件流。

        Task 的第一条事件是 SUBMITTED 快照，随后才是状态更新和 Artifact。
        这里必须 deepcopy：如果把正在被 Server 继续修改的同一个 Task
        对象交给消费者，消费者回头看第一条事件时会误以为它一开始就已
        COMPLETED，这会破坏事件日志的时间语义。
        """

        response = self.send_message(message)
        if isinstance(response, Message):
            events: list[Any] = [response]
            validate_stream(events)
            yield response
            return

        # 发送快照，避免 SUBMITTED 事件随着后续 mutation 变成 COMPLETED。
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
    """验证 Mini-A2A 的两种流模式及其顺序。

    Message mode 是一个即时回答，只允许一个 Message。
    Task mode 必须从 SUBMITTED 开始，以 terminal status 结束，并且
    COMPLETED 路径至少出现一个 Artifact。两种模式不能混用，因为消费者
    需要据此决定是读取回答，还是建立并更新一个长期任务。
    """

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
