import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from evals.rag.runner import load_cases, validate_dataset
from evals.rag.schema import RAGEvalCase


PROJECT_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = PROJECT_ROOT / "tests" / "fixtures" / "rag_eval_cases.jsonl"
MANIFEST_PATH = PROJECT_ROOT / "tests" / "fixtures" / "rag_sources.json"


CASES = load_cases(CASES_PATH)


def test_frozen_rag_dataset_is_fully_grounded() -> None:
    errors = validate_dataset(
        CASES_PATH,
        MANIFEST_PATH,
        project_root=PROJECT_ROOT,
    )

    assert errors == []
    assert len(CASES) == 10


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_case_has_structured_evidence(case: RAGEvalCase) -> None:
    if case.should_abstain:
        assert case.gold_evidence == []
        assert case.answerable_from == "not_answerable"
    else:
        assert case.gold_evidence
        assert all(evidence.page >= 1 for evidence in case.gold_evidence)
        assert all(evidence.quote.strip() for evidence in case.gold_evidence)


def test_schema_rejects_legacy_string_evidence() -> None:
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8").splitlines()[0])
    raw["gold_evidence"] = "abstract; section II.B"

    with pytest.raises(ValidationError, match="list_type"):
        RAGEvalCase.model_validate(raw)


def test_abstention_case_cannot_carry_positive_evidence() -> None:
    raw = next(case.model_dump() for case in CASES if case.should_abstain)
    raw["gold_evidence"] = [{"page": 1, "quote": "unrelated"}]

    with pytest.raises(ValidationError, match="positive evidence"):
        RAGEvalCase.model_validate(raw)


def test_answerable_case_requires_evidence() -> None:
    raw = next(case.model_dump() for case in CASES if not case.should_abstain)
    raw["gold_evidence"] = []

    with pytest.raises(ValidationError, match="at least one"):
        RAGEvalCase.model_validate(raw)
