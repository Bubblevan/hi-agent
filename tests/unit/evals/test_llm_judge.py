import json

import pytest

from evals.data_generation.llm_judge import (
    DimensionSpec,
    JudgeItem,
    JudgeResponseError,
    JudgeRubric,
    LLMJudge,
    parse_judge_json,
)


def rubric() -> JudgeRubric:
    return JudgeRubric(
        name="test-quality",
        version="v1",
        dimensions=[
            DimensionSpec(name="correctness", description="factually correct"),
            DimensionSpec(name="clarity", description="clear to the reader"),
        ],
        accept_threshold=4.0,
        review_threshold=3.0,
    )


class FakeJudgeClient:
    model = "fake-judge"

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.messages: list[list[dict[str, str]]] = []

    def invoke(self, messages: list[dict[str, str]], **kwargs: object) -> str:
        self.messages.append(messages)
        return "```json\n" + json.dumps(self.payload) + "\n```"


def item() -> JudgeItem:
    return JudgeItem(
        item_id="candidate-1",
        candidate={"problem": "2+2", "answer": 4},
        reference={"answer": 4},
        metadata={"suite": "arbitrary-not-rag"},
    )


def test_judge_is_suite_agnostic_and_derives_accept() -> None:
    client = FakeJudgeClient(
        {
            "dimension_scores": {"correctness": 5, "clarity": 4},
            "reasons": ["The answer matches the reference."],
            "strengths": ["clear"],
            "weaknesses": [],
        }
    )
    score = LLMJudge(client, rubric()).evaluate(item())

    assert score.decision == "accept"
    assert score.overall_score == 4.5
    assert "gold_evidence" not in client.messages[0][1]["content"]


def test_judge_derives_needs_review_from_threshold() -> None:
    client = FakeJudgeClient(
        {
            "dimension_scores": {"correctness": 3, "clarity": 4},
            "reasons": [],
            "strengths": [],
            "weaknesses": ["partially clear"],
        }
    )
    score = LLMJudge(client, rubric()).evaluate(item())
    assert score.decision == "needs_review"
    assert score.overall_score == 3.5


def test_parser_accepts_wrapped_json() -> None:
    assert parse_judge_json("prefix {\"scores\": {\"x\": 1}} suffix") == {
        "scores": {"x": 1}
    }


def test_dimension_mismatch_is_rejected() -> None:
    client = FakeJudgeClient(
        {
            "dimension_scores": {"correctness": 5},
            "reasons": [],
            "strengths": [],
            "weaknesses": [],
        }
    )
    with pytest.raises(JudgeResponseError, match="dimension mismatch"):
        LLMJudge(client, rubric(), retries=0).evaluate(item())
