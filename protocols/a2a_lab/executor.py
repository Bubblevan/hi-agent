"""Agent implementations kept separate from Mini-A2A protocol code."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from .models import Artifact, Message, Part, Task


class AgentExecutor(ABC):
    """The application behavior behind an A2A Task."""

    @abstractmethod
    def execute(self, message: Message, task: Task) -> Artifact:
        raise NotImplementedError


class StaticArtifactExecutor(AgentExecutor):
    """Useful for deterministic lifecycle tests."""

    def __init__(self, artifact: Artifact | None = None) -> None:
        self.artifact = artifact or Artifact(
            artifact_id="artifact-static",
            name="result",
            description="A deterministic teaching result",
            parts=[Part(text="completed")],
        )

    def execute(self, message: Message, task: Task) -> Artifact:
        return self.artifact


class CodingAgentExecutor(AgentExecutor):
    """A small bridge from A2A task execution to the existing MCP Host."""

    def __init__(self, mcp_host: Any) -> None:
        self.mcp_host = mcp_host

    def execute(self, message: Message, task: Task) -> Artifact:
        selection = self.mcp_host.select_tools(message.text)
        if not selection.selected:
            raise RuntimeError("Coding Agent found no relevant MCP tool")

        entry = next(
            (
                candidate
                for candidate in selection.selected
                if candidate.original_tool_name == "grep_code"
            ),
            selection.selected[0],
        )
        execution = self.mcp_host.execute(
            entry.canonical_tool_name,
            {"query": message.text},
            selected_by="a2a_coding_executor",
            selection_reason=selection.reasons[
                entry.canonical_tool_name
            ],
        )
        return Artifact(
            artifact_id=f"artifact-{uuid4().hex}",
            name="repository-research",
            description="Evidence collected by Coding Agent through MCP.",
            parts=[
                Part(
                    data={
                        "selected_tool": entry.canonical_tool_name,
                        "result": execution.result,
                        "trace": execution.trace.as_dict(),
                    }
                ),
                Part(
                    text=(
                        "Coding Agent completed an MCP-backed repository "
                        "inspection."
                    )
                ),
            ],
        )

