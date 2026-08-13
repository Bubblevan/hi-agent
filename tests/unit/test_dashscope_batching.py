from types import SimpleNamespace

import pytest

from core.embeddings.dashscope import (
    DashScopeEmbedder,
    EmbeddingRequestError,
    EmbeddingResponseError,
)


class FakeEmbeddingsAPI:
    def __init__(self, responses=None, failures=None):
        self.responses = list(responses or [])
        self.failures = list(failures or [])
        self.calls = []

    def create(self, *, model, input):
        self.calls.append({"model": model, "input": input})
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        if not self.responses:
            raise AssertionError("fake API has no response left")
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, api):
        self.embeddings = api


def response(*vectors, indexes=None):
    items = []
    for position, vector in enumerate(vectors):
        item = {"embedding": vector}
        if indexes is not None:
            item["index"] = indexes[position]
        items.append(SimpleNamespace(**item))
    return SimpleNamespace(data=items)


def make_embedder(api, **kwargs):
    embedder = DashScopeEmbedder(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        dimension=3,
        **kwargs,
    )
    embedder.client = FakeClient(api)
    return embedder


def test_documents_are_sent_in_batches_and_order_is_preserved() -> None:
    api = FakeEmbeddingsAPI(
        responses=[
            response([1, 0, 0], [0, 1, 0]),
            response([0, 0, 1]),
        ]
    )
    embedder = make_embedder(api, batch_size=2, max_retries=0)

    vectors = embedder.embed_documents(["a", "b", "c"])

    assert vectors == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert [call["input"] for call in api.calls] == [["a", "b"], ["c"]]
    assert all(call["model"] == "qwen3.7-text-embedding" for call in api.calls)


def test_requested_batch_size_is_capped_at_provider_limit() -> None:
    api = FakeEmbeddingsAPI(
        responses=[
            response(*([[1, 0, 0]] * 20)),
            response([0, 1, 0]),
        ]
    )
    embedder = make_embedder(api, batch_size=64, max_retries=0)

    embedder.embed_documents([str(index) for index in range(21)])

    assert [len(call["input"]) for call in api.calls] == [20, 1]


def test_provider_indexes_restore_input_order() -> None:
    api = FakeEmbeddingsAPI(
        responses=[response([0, 1, 0], [1, 0, 0], indexes=[1, 0])]
    )
    embedder = make_embedder(api, batch_size=8, max_retries=0)

    assert embedder.embed_documents(["first", "second"]) == [
        [1, 0, 0],
        [0, 1, 0],
    ]


def test_retryable_failure_uses_exponential_backoff() -> None:
    class RateLimitFailure(Exception):
        status_code = 429

    api = FakeEmbeddingsAPI(
        failures=[RateLimitFailure("busy"), RateLimitFailure("busy")],
        responses=[response([1, 2, 3])],
    )
    sleeps = []
    embedder = make_embedder(
        api,
        batch_size=4,
        max_retries=2,
        retry_backoff_seconds=0.25,
        sleep_fn=sleeps.append,
    )

    assert embedder.embed_documents(["retry me"]) == [[1.0, 2.0, 3.0]]
    assert len(api.calls) == 3
    assert sleeps == [0.25, 0.5]


def test_non_retryable_failure_fails_without_sleep() -> None:
    api = FakeEmbeddingsAPI(failures=[ValueError("invalid request")])
    sleeps = []
    embedder = make_embedder(api, max_retries=3, sleep_fn=sleeps.append)

    with pytest.raises(EmbeddingRequestError) as error:
        embedder.embed_documents(["bad request"])

    assert error.value.attempts == 1
    assert error.value.batch_start == 0
    assert sleeps == []


def test_retryable_failure_reports_batch_after_exhaustion() -> None:
    class ServiceFailure(Exception):
        status_code = 503

    api = FakeEmbeddingsAPI(failures=[ServiceFailure("down"), ServiceFailure("down")])
    embedder = make_embedder(api, batch_size=2, max_retries=1, retry_backoff_seconds=0)

    with pytest.raises(EmbeddingRequestError) as error:
        embedder.embed_documents(["one", "two", "three"])

    assert error.value.batch_start == 0
    assert error.value.batch_size == 2
    assert error.value.attempts == 2
    assert len(api.calls) == 2


def test_malformed_response_does_not_retry_or_return_partial_vectors() -> None:
    api = FakeEmbeddingsAPI(responses=[response([1, 0, 0])])
    embedder = make_embedder(api, max_retries=3)

    with pytest.raises(EmbeddingResponseError, match="returned 1 vectors"):
        embedder.embed_documents(["one", "two"])

    assert len(api.calls) == 1


def test_dimension_mismatch_stops_before_the_next_batch() -> None:
    api = FakeEmbeddingsAPI(
        responses=[
            response([1, 0]),
            response([0, 1, 0]),
        ]
    )
    embedder = make_embedder(api, batch_size=1, max_retries=0)

    with pytest.raises(EmbeddingResponseError, match="dimension mismatch"):
        embedder.embed_documents(["wrong", "never requested"])

    assert len(api.calls) == 1


def test_empty_and_blank_inputs_are_rejected_before_network_call() -> None:
    api = FakeEmbeddingsAPI()
    embedder = make_embedder(api)

    assert embedder.embed_documents([]) == []
    with pytest.raises(ValueError, match="must not be blank"):
        embedder.embed_documents(["ok", " "])
    assert api.calls == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"batch_size": 0}, "batch_size"),
        ({"max_retries": -1}, "max_retries"),
        ({"retry_backoff_seconds": -0.1}, "retry_backoff_seconds"),
    ],
)
def test_retry_configuration_is_validated(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        make_embedder(FakeEmbeddingsAPI(), **kwargs)
