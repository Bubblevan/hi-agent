"""Mini-A2A 的进程内 Client。

这个 Client 故意很薄：它帮助测试“调用方看到的 A2A contract”，但不负责
重造 HTTP、JSON-RPC、REST、gRPC、认证或重试。那些属于官方 A2A SDK 的
binding 和 runtime 范围。
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import AgentCard, Message, Task
from .protocol import MiniA2AServer


@dataclass(slots=True)
class MiniA2AClient:
    """把远端调用形状投影成本地方法，方便学习核心语义。"""

    server: MiniA2AServer

    def get_agent_card(self) -> AgentCard:
        """发现对方 Agent 的能力名片。"""
        return self.server.get_agent_card()

    def send_message(self, message: Message) -> Message | Task:
        """发送一条 Message，可能得到即时 Message 或 Task。"""
        return self.server.send_message(message)

    def get_task(self, task_id: str) -> Task:
        """读取已创建的 Task。"""
        return self.server.get_task(task_id)

    def send_message_stream(self, message: Message):
        """订阅一次教学版流式生命周期。"""
        return self.server.send_message_stream(message)
