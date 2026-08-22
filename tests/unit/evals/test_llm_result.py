from types import SimpleNamespace

from core.llm_client import MyLLMClient
from core.llm_result import LLMResult


def test_llm_result_marks_provider_errors():
    result = LLMResult(content="failed", model="test", error="timeout")

    assert result.provider_error is True


def test_invoke_with_metadata_extracts_openai_compatible_usage(monkeypatch):
    response = SimpleNamespace(
        model="returned-model",
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="answer"),
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=11,
            completion_tokens=7,
            prompt_tokens_details=SimpleNamespace(cached_tokens=2),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=3),
        ),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            return response

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )
    monkeypatch.setattr("core.llm_client.OpenAI", lambda **kwargs: fake_client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    client = MyLLMClient(model="configured-model")
    result = client.invoke_with_metadata(
        [{"role": "user", "content": "hi"}],
        temperature=0,
        max_tokens=32,
    )

    assert result == LLMResult(
        content="answer",
        model="returned-model",
        finish_reason="length",
        prompt_tokens=11,
        completion_tokens=7,
        reasoning_tokens=3,
        cached_tokens=2,
    )
    assert client.invoke([{"role": "user", "content": "hi"}]) == "answer"
