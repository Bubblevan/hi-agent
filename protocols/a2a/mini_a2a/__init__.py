"""Mini-A2A teaching contract for Hi-Agent."""

"""Mini-A2A 学习夹具。

导出的对象代表最小 contract；真正的生产集成应放到 protocols.a2a.integration，
并依赖官方 a2a-sdk，而不是继续扩张这个目录。
"""

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
