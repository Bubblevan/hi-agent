"""Mini-A2A 的核心数据模型。

这里故意只保留 A2A v1 学习时最值得亲手理解的对象：

    AgentCard -> Message -> Task -> Artifact

这不是官方 SDK 的替代品，而是一组可读、可测试的学习夹具。模型上的
校验表达的是协议语义，例如 Part 不能同时有两种载荷、Task 的身份不能
为空；真正的网络序列化、认证和传输仍然交给官方 A2A SDK。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    """消息发送者。

    Mini-A2A 只需要区分用户和 Agent。真实 A2A 还会围绕消息历史、上下文
    和远端 Agent 进行更完整的建模，但这里先把“谁说的”讲清楚。
    """

    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Part:
    """消息或交付物中的一个内容片段。

    A2A 的 Message 和 Artifact 都由 Part 组成，而不是直接塞一个字符串。
    这样同一条消息既可以包含自然语言，也可以包含结构化数据。教学版只
    实现 text 和 data 两种 Part；恰好二选一的约束对应了一个重要边界：
    调用方必须明确自己传的是文本还是结构化内容。
    """

    text: str | None = None
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        # 两者都没有，消费者不知道如何解释；两者都有，载荷语义不明确。
        if (self.text is None) == (self.data is None):
            raise ValueError("Part must contain exactly one of text or data")
        # 空文本通常意味着调用方误把缺失内容当成了有效 Part。
        if self.text is not None and not self.text.strip():
            raise ValueError("Part.text must not be blank")


@dataclass(frozen=True, slots=True)
class Message:
    """一次通信 turn，而不是一项持续工作的任务。

    Message 用来表达“我说了什么”。如果对方可以立即回答，它可能直接
    返回另一个 Message；如果请求需要规划、工具调用或等待，则 Server
    会把它纳入 Task.history，并创建一个可跟踪的 Task。

    task_id 和 context_id 的职责不同：
    - task_id 指向一次具体工作；
    - context_id 指向一段连续对话或业务上下文。

    因此同一个 context 可以产生多个 Task，而一个 Task 也可以在生命周期
    中积累多条 Message。
    """

    message_id: str
    role: Role
    parts: list[Part]
    task_id: str | None = None
    context_id: str | None = None

    def __post_init__(self) -> None:
        # message_id 让消息能被历史、事件和日志稳定引用。
        if not self.message_id.strip():
            raise ValueError("message_id must not be blank")
        # 空 parts 会产生一个“存在但没有内容”的通信 turn。
        if not self.parts:
            raise ValueError("Message.parts must not be empty")

    @property
    def text(self) -> str:
        return "\n".join(
            part.text for part in self.parts if part.text is not None
        )


class TaskState(StrEnum):
    """Mini-A2A 的最小任务状态机。

    真实 A2A v1 还覆盖 input-required、auth-required、canceled 等更丰富
    的中断或终止状态。教学版先固定四个状态，是为了把最小生命周期看得
    清楚，而不是声称这四个状态覆盖完整规范。
    """

    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TaskStatus:
    """Task 当前状态以及可选的状态说明消息。"""

    state: TaskState
    message: Message | None = None


@dataclass(frozen=True, slots=True)
class Artifact:
    """Task 的可交付成果。

    Message 是交流过程，Artifact 是工作结果。对 Coding Agent 来说，补丁、
    测试报告、变更文件清单都比一句“完成了”更适合作为 Artifact。Artifact
    同样由 Part 组成，因此可以同时返回人类可读摘要和机器可消费的数据。
    """

    artifact_id: str
    name: str
    description: str
    parts: list[Part]

    def __post_init__(self) -> None:
        # Artifact 需要稳定身份，便于流式更新、去重和审计。
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be blank")
        if not self.name.strip():
            raise ValueError("Artifact.name must not be blank")
        if not self.parts:
            raise ValueError("Artifact.parts must not be empty")


@dataclass(slots=True)
class Task:
    """一项有生命周期、历史和交付物的工作委托。

    Task 是 Mini-A2A 的核心，不等同于 MCP 的一次 tools/call。远端 Agent
    可以在 Task 内部思考、调用多个工具、重试并最终产出 Artifact；调用方
    不需要知道这些内部步骤，只需要观察状态和交付物。
    """

    id: str
    context_id: str
    status: TaskStatus
    artifacts: list[Artifact] = field(default_factory=list)
    history: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        # task id 与 context id 都是跨事件、跨日志关联请求的锚点。
        if not self.id.strip():
            raise ValueError("Task.id must not be blank")
        if not self.context_id.strip():
            raise ValueError("Task.context_id must not be blank")


@dataclass(frozen=True, slots=True)
class AgentSkill:
    """Agent 对外宣称的一项高层能力。

    注意它描述的是 Agent 能完成的工作，例如 repository-inspection 或
    repair_repository，而不是内部 MCP 工具名 grep_code、read_file。这个
    层次差异正是“Agent 不能简单当成 Tool”的一个具体体现。
    """

    id: str
    name: str
    description: str

    def __post_init__(self) -> None:
        for field_name in ("id", "name", "description"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"AgentSkill.{field_name} must not be blank")


@dataclass(frozen=True, slots=True)
class AgentCard:
    """远端 Agent 的 discovery 名片。

    AgentCard 回答“你是谁、你会什么、我应该联系哪里”，而不是暴露
    Agent 内部的 MCP tool catalog。真实 A2A 会继续包含认证要求、能力
    开关和更丰富的 skill 描述；Mini 版先固定 discovery 的最小心智模型。
    """

    name: str
    description: str
    version: str
    protocol_version: str
    url: str
    skills: list[AgentSkill]

    def __post_init__(self) -> None:
        # 名片如果缺少身份或 endpoint，调用方无法进行可靠发现。
        for field_name in ("name", "version", "protocol_version", "url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if not self.skills:
            raise ValueError("AgentCard.skills must not be empty")
