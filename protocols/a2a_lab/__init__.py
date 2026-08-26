"""Mini-A2A teaching contract for Hi-Agent."""

from .client import MiniA2AClient
from .executor import AgentExecutor, CodingAgentExecutor, StaticArtifactExecutor
from .models import (
    AgentCard,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Role,
    Task,
    TaskState,
    TaskStatus,
)
from .protocol import (
    InvalidTaskTransition,
    MiniA2AServer,
    TaskArtifactUpdateEvent,
    TaskStatusUpdateEvent,
    transition_task,
    validate_stream,
)

__all__ = [
    "AgentCard",
    "AgentExecutor",
    "AgentSkill",
    "Artifact",
    "CodingAgentExecutor",
    "InvalidTaskTransition",
    "Message",
    "MiniA2AClient",
    "MiniA2AServer",
    "Part",
    "Role",
    "StaticArtifactExecutor",
    "Task",
    "TaskArtifactUpdateEvent",
    "TaskState",
    "TaskStatus",
    "TaskStatusUpdateEvent",
    "transition_task",
    "validate_stream",
]

