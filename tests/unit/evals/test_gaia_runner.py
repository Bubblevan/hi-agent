from pathlib import Path

import pytest

from evals.llm_evals.gaia_runner import (
    GAIAEvaluator,
    GAIADataset,
    GAIAItem,
    build_prompt,
    extract_answer,
    export_jsonl,
    normalize_answer,
)


def test_normalize_answer_handles_numbers_articles_and_lists() -> None:
    assert normalize_answer("$1,234.00") == "1234.00"
    assert normalize_answer("The answer.") == "answer"
    assert normalize_answer("zebra, Apple") == "apple,zebra"


def test_normalize_answer_contracts_are_explicit() -> None:
    assert normalize_answer("$1,234.56") == "1234.56"
    assert normalize_answer("The United States") == "united states"
    assert normalize_answer("Paris, London, Berlin") == "berlin,london,paris"
    assert normalize_answer("  12% ") == "12"


def test_extract_answer_prefers_gaia_marker() -> None:
    response = "I checked the file.\nFINAL ANSWER: [42]\n"
    assert extract_answer(response) == "42"


def test_dataset_rejects_attachment_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "gaia"
    (root / "2023" / "validation").mkdir(parents=True)
    dataset = GAIADataset(root)
    with pytest.raises(ValueError, match="escapes split root"):
        dataset.resolve_attachment("../../outside.txt")


def test_dataset_resolves_attachment_inside_split_root(tmp_path: Path) -> None:
    root = tmp_path / "gaia"
    split_root = root / "2023" / "validation"
    split_root.mkdir(parents=True)
    attachment = split_root / "notes.txt"
    attachment.write_text("hello", encoding="utf-8")
    dataset = GAIADataset(root)

    assert dataset.resolve_attachment("notes.txt") == attachment.resolve()


def test_build_prompt_mentions_attachment_tool_when_needed(tmp_path: Path) -> None:
    attachment = tmp_path / "data.txt"
    item = GAIAItem("one", "Read the attached data", 1, "42", "data.txt", None, attachment)

    prompt = build_prompt(item)

    assert "one" in prompt
    assert "data.txt" in prompt
    assert "read_attachment" in prompt


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


def test_evaluator_records_agent_errors_and_unscorable_cases() -> None:
    items = [
        GAIAItem("error", "question", 1, "42", None, None, None),
        GAIAItem("test", "question", 1, None, None, None, None),
    ]

    class FailingAgent:
        def run(self, prompt: str, **kwargs: object) -> str:
            raise RuntimeError("boom")

    report = GAIAEvaluator(items, FailingAgent, samples=0).evaluate()

    assert report["scorable_samples"] == 1
    assert report["correct_samples"] == 0
    assert report["accuracy"] == 0.0
    assert report["cases"][0]["error"] == "RuntimeError: boom"
    assert report["cases"][1]["scorable"] is False


def test_export_jsonl_does_not_copy_expected_answer(tmp_path: Path) -> None:
    output = tmp_path / "answers.jsonl"
    results = {
        "cases": [
            {"task_id": "one", "predicted": "42", "response": "FINAL ANSWER: 42"}
        ]
    }

    export_jsonl(results, output)
    row = output.read_text(encoding="utf-8")

    assert '"task_id": "one"' in row
    assert '"model_answer": "42"' in row
    assert "expected" not in row
