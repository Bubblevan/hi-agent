from collections.abc import Iterable


class FakeLLM:
    """Small deterministic LLM double used by offline unit tests."""

    def __init__(self, responses: Iterable[str], stream_chunks: Iterable[str] = ()):
        self.model = "fake-model"
        self.responses = list(responses)
        self.stream_chunks = list(stream_chunks)
        self.invocations = []

    def invoke(self, messages, **kwargs):
        self.invocations.append((messages, kwargs))
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self.responses.pop(0)

    def stream_invoke(self, messages, **kwargs):
        self.invocations.append((messages, kwargs))
        yield from self.stream_chunks
