"""Official A2A SDK integration for Hi-Agent.

mini_a2a is the readable protocol learning fixture. This package is the
engineering boundary that uses the official a2a-sdk for v1 types, routing,
streaming, and task storage.
"""

from .client import A2AResearchClient, build_user_message
from .server import (
    MCPBackedA2AExecutor,
    build_coding_agent_app,
    build_coding_agent_card,
)

__all__ = [
    "A2AResearchClient",
    "MCPBackedA2AExecutor",
    "build_coding_agent_app",
    "build_coding_agent_card",
    "build_user_message",
]
