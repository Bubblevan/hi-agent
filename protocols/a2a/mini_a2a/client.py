"""A deliberately thin Mini-A2A client."""

from __future__ import annotations

from dataclasses import dataclass

from .models import AgentCard, Message, Task
from .protocol import MiniA2AServer


@dataclass(slots=True)
class MiniA2AClient:
    server: MiniA2AServer

    def get_agent_card(self) -> AgentCard:
        return self.server.get_agent_card()

    def send_message(self, message: Message) -> Message | Task:
        return self.server.send_message(message)

    def get_task(self, task_id: str) -> Task:
        return self.server.get_task(task_id)

    def send_message_stream(self, message: Message):
        return self.server.send_message_stream(message)

