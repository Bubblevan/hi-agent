from pathlib import Path
from types import SimpleNamespace

from core.llm_result import LLMResult
from evals.context.runner import run_evaluation, write_report


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "context_llm_eval_cases.jsonl"


class FakeMetadataProvider:
    model = "fake-context-model"

    def __init__(self) -> None:
        self.calls: list[list[dict[str, str]]] = []

    def invoke_with_metadata(self, payload, **kwargs):
        self.calls.append(payload)
        return LLMResult(
            content=(
                "expand backfill caplog monkeypatch "
                "checkpoint_id replay"
            ),
            model=self.model,
            finish_reason="stop",
            prompt_tokens=100,
            completion_tokens=20,
        )


def test_runner_scores_repeated_fixture_and_writes_report(tmp_path):
    provider = FakeMetadataProvider()

    report = run_evaluation(FIXTURE, provider, repeats=2)

    assert report["case_count"] == 3
    assert report["total_attempts"] == 6
    assert report["successful_attempts"] == 6
    assert report["metrics"] == {
        "exact_match": 1.0,
        "must_select_recall": 1.0,
        "distractor_exclusion": 1.0,
        "required_coverage": 1.0,
        "forbidden_leakage": 0.0,
        "truncation": 0.0,
        "provider_error": 0.0,
    }
    assert len(provider.calls) == 6
    assert all(
        "old-notes.md" not in message["content"]
        for payload in provider.calls
        for message in payload
    )

    output = write_report(report, tmp_path / "context-eval.json")

    assert output.exists()
    assert '"total_attempts": 6' in output.read_text(encoding="utf-8")
