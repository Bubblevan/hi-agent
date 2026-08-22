import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from context.budget import BudgetExceededError
from context.selector import select_items
from evals.context.schema import ContextEvalCase


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = PROJECT_ROOT / "tests" / "fixtures" / "context_contract_cases.jsonl"


def load_cases() -> list[ContextEvalCase]:
    with DATASET_PATH.open(encoding="utf-8") as file:
        return [
            ContextEvalCase.model_validate(json.loads(line))
            for line in file
            if line.strip()
        ]


CASES = load_cases()


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_context_case_is_executable(case: ContextEvalCase):
    items = [item.to_domain() for item in case.items]
    budget = case.budget.to_domain()

    if case.expected.outcome == "error":
        with pytest.raises(BudgetExceededError) as error:
            select_items(items, budget)
        assert type(error.value).__name__ == case.expected.error_type
        return

    selected = select_items(items, budget)
    selected_ids = [item.item_id for item in selected]
    dropped_ids = [
        item.item_id
        for item in items
        if not item.required and item.item_id not in set(selected_ids)
    ]

    assert selected_ids == case.expected.selected_item_ids
    assert dropped_ids == case.expected.dropped_item_ids


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.case_id)
def test_success_case_expected_ids_partition_items(case: ContextEvalCase):
    if case.expected.outcome != "success":
        pytest.skip("error cases do not have a selection partition")

    item_ids = {item.item_id for item in case.items}
    selected_ids = set(case.expected.selected_item_ids)
    dropped_ids = set(case.expected.dropped_item_ids)
    optional_ids = {item.item_id for item in case.items if not item.required}
    required_ids = item_ids - optional_ids

    assert selected_ids.isdisjoint(dropped_ids)
    assert selected_ids | dropped_ids == item_ids
    assert required_ids <= selected_ids
    assert optional_ids == (selected_ids & optional_ids) | dropped_ids
    assert dropped_ids <= optional_ids


def test_dataset_rejects_duplicate_item_ids():
    raw = {
        "case_id": "duplicate",
        "suite": "context-contract-v2",
        "task": "test",
        "budget": {"soft_limit": 10, "hard_limit": 20, "output_reserve": 5},
        "items": [
            {
                "item_id": "same",
                "kind": "task",
                "content": "one",
                "source": "test",
                "priority": 1,
                "required": True,
                "token_count": 1,
            },
            {
                "item_id": "same",
                "kind": "note",
                "content": "two",
                "source": "test",
                "priority": 1,
                "required": False,
                "token_count": 1,
            },
        ],
        "expected": {"outcome": "success"},
    }

    with pytest.raises(ValidationError, match="unique item_id"):
        ContextEvalCase.model_validate(raw)


def test_dataset_rejects_success_case_with_error_type():
    raw = {
        "case_id": "bad-expected",
        "suite": "context-contract-v2",
        "task": "test",
        "budget": {"soft_limit": 10, "hard_limit": 20, "output_reserve": 5},
        "items": [
            {
                "item_id": "task",
                "kind": "task",
                "content": "do it",
                "source": "test",
                "priority": 1,
                "required": True,
                "token_count": 1,
            }
        ],
        "expected": {"outcome": "success", "error_type": "BudgetExceededError"},
    }

    with pytest.raises(ValidationError, match="error_type"):
        ContextEvalCase.model_validate(raw)
