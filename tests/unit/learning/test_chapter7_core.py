from types import SimpleNamespace

import pytest

from core.agent_base import MyAgent
from core.config import Config
from core.llm_client import MyLLMClient
from core.message import MyMessage

from .fakes import FakeLLM


class ConcreteAgent(MyAgent):
    def run(self, input_text: str, **kwargs) -> str:
        response = self.llm.invoke(
            self.get_history_dicts() + [MyMessage.user(input_text).to_dict()],
            **kwargs,
        )
        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(response))
        return response


def test_message_factory_and_api_shape():
    message = MyMessage.user("hello")

    assert str(message) == "[user] hello"
    assert message.to_dict() == {"role": "user", "content": "hello"}
    assert MyMessage.system("rules").role == "system"
    assert MyMessage.assistant("answer").role == "assistant"


def test_config_reads_environment(monkeypatch):
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TEMPERATURE", "0.2")
    monkeypatch.setenv("MAX_TOKENS", "128")

    config = Config.from_env()

    assert config.debug is True
    assert config.log_level == "DEBUG"
    assert config.temperature == pytest.approx(0.2)
    assert config.max_tokens == 128


def test_llm_client_provider_detection_and_invocation(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            if kwargs["stream"]:
                return [
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]),
                    SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))]),
                ]
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))]
            )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    monkeypatch.setattr("core.llm_client.OpenAI", lambda **kwargs: fake_client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = MyLLMClient(model="test-model")

    assert client.provider == "openai"
    assert client.base_url == "https://api.openai.com/v1"
    assert client.invoke([{"role": "user", "content": "hi"}]) == "answer"
    assert list(client.stream_invoke([])) == ["A", "B"]


def test_agent_history_is_bounded_and_clear_keeps_system_prompt():
    agent = ConcreteAgent(
        "tester",
        FakeLLM(["one", "two"]),
        system_prompt="system rules",
        config=Config(max_history_length=3),
    )

    assert agent.run("first") == "one"
    assert agent.run("second") == "two"
    assert len(agent.get_history()) == 3

    agent.clear_history()

    assert [message.role for message in agent.get_history()] == ["system"]
