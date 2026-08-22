import json

from evals.data_generation.rag_generator import (
    build_paged_document,
    generate_candidates,
    parse_jsonl,
    serialize_cases,
)
from evals.data_generation.rag_validator import validate_candidates


def candidate(*, case_id="case-1", quote="grounded quote", page=1):
    return {
        "case_id": case_id,
        "suite": "rag-generated-v1",
        "source_id": "source",
        "question": f"What does {case_id} say?",
        "answer_type": "fact",
        "difficulty": "easy",
        "answerable_from": "single_page",
        "expected_terms": ["grounded"],
        "forbidden_terms": [],
        "should_abstain": False,
        "gold_evidence": [{"page": page, "quote": quote}],
    }


class FakeCandidateClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def invoke(self, messages, **kwargs):
        self.messages.append((messages, kwargs))
        return self.responses.pop(0)


def test_build_paged_document_preserves_explicit_page_numbers():
    document = build_paged_document(["first", "second"], page_numbers=[3, 7])

    assert document == "=== PAGE 3 ===\nfirst\n\n=== PAGE 7 ===\nsecond"


def test_parse_jsonl_accepts_fenced_jsonl_and_json_arrays():
    row = candidate()

    assert parse_jsonl("```json\n" + json.dumps(row) + "\n```") == [row]
    assert parse_jsonl(json.dumps([row])) == [row]


def test_generator_batches_one_request_per_page_and_injects_source_id():
    row = candidate()
    row.pop("source_id")
    client = FakeCandidateClient([json.dumps(row), json.dumps(row)])

    candidates = generate_candidates(
        client,
        ["page one grounded", "page two grounded"],
        source_id="source",
        candidates_per_page=(1, 1),
    )

    assert len(client.messages) == 2
    assert [item["source_id"] for item in candidates] == ["source", "source"]
    assert "=== PAGE 1 ===" in client.messages[0][0][1]["content"]
    assert "=== PAGE 2 ===" in client.messages[1][0][1]["content"]


def test_validator_keeps_invalid_and_duplicate_candidates_for_review():
    valid = candidate()
    duplicate = dict(valid)
    invalid = candidate(case_id="case-2", quote="not in source")

    report = validate_candidates(
        [valid, duplicate, invalid],
        ["grounded quote is present here"],
        source_id="source",
    )

    assert len(report.accepted) == 1
    assert report.duplicate_count == 1
    assert len(report.review_queue) == 2
    assert any("duplicate candidate" in error for error in report.review_queue[0].errors)
    assert any("quote is not present" in error for error in report.review_queue[1].errors)


def test_accepted_candidates_serialize_as_schema_compatible_jsonl():
    report = validate_candidates(
        [candidate()],
        ["grounded quote is present here"],
        source_id="source",
    )

    rows = [json.loads(line) for line in serialize_cases(report.accepted).splitlines()]

    assert rows[0]["gold_evidence"] == [{"page": 1, "quote": "grounded quote"}]
