from pathlib import Path

import pytest

from evals.llm_evals.gaia_runner import (
    GAIAEvaluator,
    GAIADataset,
    GAIAItem,
    extract_answer,
    normalize_answer,
)


def test_normalize_answer_handles_numbers_articles_and_lists() -> None:
    assert normalize_answer("$1,234.00") == "1234.00"
    assert normalize_answer("The answer.") == "answer"
    assert normalize_answer("zebra, Apple") == "apple,zebra"


def test_extract_answer_prefers_gaia_marker() -> None:
    response = "I checked the file.\nFINAL ANSWER: [42]\n"
    assert extract_answer(response) == "42"


def test_dataset_rejects_attachment_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "gaia"
    (root / "2023" / "validation").mkdir(parents=True)
    dataset = GAIADataset(root)
    with pytest.raises(ValueError, match="escapes split root"):
        dataset.resolve_attachment("../../outside.txt")


def test_evaluator_preserves_case_evidence() -> None:
    items = [
        GAIAItem("one", "question", 1, "42", None, None, None),
        GAIAItem("two", "question", 2, "apple,zebra", None, None, None),
    ]

    class FakeAgent:
        def __init__(self, answer: str) -> None:
            self.answer = answer

        def run(self, prompt: str, **kwargs: object) -> str:
            return self.answer

    answers = iter(["FINAL ANSWER: 42", "FINAL ANSWER: zebra, apple"])
    results = GAIAEvaluator(
        items,
        lambda: FakeAgent(next(answers)),
        samples=0,
    ).evaluate()

    assert results["correct_samples"] == 2
    assert results["accuracy"] == 1.0
    assert all(case["scorable"] for case in results["cases"])


def test_test_split_never_exposes_answer(tmp_path: Path) -> None:
    root = tmp_path / "gaia"
    split_root = root / "2023" / "test"
    split_root.mkdir(parents=True)
    dataset = GAIADataset(root, split="test")
    row = {
        "task_id": "secret",
        "Question": "question",
        "Level": 1,
        "Final answer": "private",
    }
    item = dataset._standardize(row)
    assert item.final_answer is None
