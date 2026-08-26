"""Mini-A2A 的应用侧 Executor。

协议只规定“收到消息后如何表示 Task 和 Artifact”；Executor 才决定 Agent
具体做什么。把两者拆开有两个学习收益：

1. StaticArtifactExecutor 可以测试生命周期，而不需要真实工具；
2. CodingAgentExecutor 可以展示 A2A Task -> MCP Host -> Artifact 的桥接。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from uuid import uuid4

from .models import Artifact, Message, Part, Task


class AgentExecutor(ABC):
    """A2A Task 背后的 Agent 行为接口。"""

    @abstractmethod
    def execute(self, message: Message, task: Task) -> Artifact:
        raise NotImplementedError


class StaticArtifactExecutor(AgentExecutor):
    """为 contract 测试提供确定性 Artifact 的 Executor。"""

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
    """把 A2A 任务委托给现有 MCP Host 的小型桥接器。

    AgentCard 对外表达的是 repository-inspection 这类高层能力；实际执行
    时，Coding Agent 才通过 MCP Host 选择 grep_code 等底层工具。这个例子
    直观展示了：

        A2A = Agent 与 Agent 之间委托工作
        MCP = Agent 内部访问工具和上下文能力
    """

    def __init__(self, mcp_host: Any) -> None:
        self.mcp_host = mcp_host

    def execute(self, message: Message, task: Task) -> Artifact:
        # 先按自然语言任务选择工具，而不是把全部 MCP catalog 塞进上下文。
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
        # MCP Host 统一负责 policy、执行、trace；Executor 只组合业务输入
        # 并把执行证据包装成 A2A Artifact。
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
