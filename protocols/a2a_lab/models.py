"""The five Mini-A2A objects used by the learning contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Part:
    text: str | None = None
    data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if (self.text is None) == (self.data is None):
            raise ValueError("Part must contain exactly one of text or data")
        if self.text is not None and not self.text.strip():
            raise ValueError("Part.text must not be blank")


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    role: Role
    parts: list[Part]
    task_id: str | None = None
    context_id: str | None = None

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise ValueError("message_id must not be blank")
        if not self.parts:
            raise ValueError("Message.parts must not be empty")

    @property
    def text(self) -> str:
        return "\n".join(
            part.text for part in self.parts if part.text is not None
        )


@dataclass(frozen=True, slots=True)
class TaskStatus:
    state: "TaskState"
    message: Message | None = None


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Artifact:
    artifact_id: str
    name: str
    description: str
    parts: list[Part]

    def __post_init__(self) -> None:
        if not self.artifact_id.strip():
            raise ValueError("artifact_id must not be blank")
        if not self.name.strip():
            raise ValueError("Artifact.name must not be blank")
        if not self.parts:
            raise ValueError("Artifact.parts must not be empty")


@dataclass(slots=True)
class Task:
    id: str
    context_id: str
    status: TaskStatus
    artifacts: list[Artifact] = field(default_factory=list)
    history: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Task.id must not be blank")
        if not self.context_id.strip():
            raise ValueError("Task.context_id must not be blank")


@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    name: str
    description: str
    version: str
    protocol_version: str
    url: str
    skills: list[AgentSkill]

    def __post_init__(self) -> None:
        for field_name in ("name", "version", "protocol_version", "url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be blank")
        if not self.skills:
            raise ValueError("AgentCard.skills must not be empty")

