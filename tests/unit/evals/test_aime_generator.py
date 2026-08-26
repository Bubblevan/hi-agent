import json

import pytest

from evals.data_generation.aime_generator import (
    AIMECandidate,
    generate_candidates,
    parse_candidates,
    validate_candidates,
)


def candidate(case_id="aime-1", answer=42, problem="A unique problem"):
    return {
        "case_id": case_id,
        "problem": problem,
        "solution": "Compute the expression carefully; the final answer is 42.",
        "answer": answer,
        "topic": "algebra",
        "difficulty": "medium",
    }


class FakeAIMEClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def invoke(self, messages, **kwargs):
        self.messages.append((messages, kwargs))
        return self.responses.pop(0)


def test_parse_candidates_accepts_fenced_array():
    row = candidate()
    assert parse_candidates("```json\n" + json.dumps([row]) + "\n```") == [row]


def test_generator_uses_one_request_per_topic():
    client = FakeAIMEClient([json.dumps([candidate("a"), candidate("b", problem="Second")])])
    rows = generate_candidates(client, ["algebra"], count_per_topic=2)

    assert len(rows) == 2
    assert len(client.messages) == 1
    assert "Topic: algebra" in client.messages[0][0][1]["content"]


def test_validator_keeps_invalid_and_duplicate_candidates_for_review():
    duplicate = candidate("a", problem="A unique problem")
    invalid = candidate("bad", answer=1000, problem="Out of range")
    report = validate_candidates([duplicate, dict(duplicate), invalid])

    assert len(report.accepted) == 1
    assert len(report.review_queue) == 2
    assert any("duplicate problem" in error for error in report.review_queue[0].errors)
    assert any("0..999" in error for error in report.review_queue[1].errors)


def test_answer_code_is_canonical_three_digits():
    assert AIMECandidate.model_validate(candidate(answer=7)).answer_code == "007"


def test_boolean_is_not_an_aime_answer():
    with pytest.raises(ValueError, match="0..999"):
        AIMECandidate.model_validate(candidate(answer=True))
