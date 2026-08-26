import json

from evals.data_generation.pairwise_judge import (
    PairwiseJudge,
    PairwiseItem,
    _display_order,
)


class FakePairwiseClient:
    model = "fake-judge"

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def invoke(self, messages, **kwargs):
        self.messages.append((messages, kwargs))
        return self.responses.pop(0)


def item(pair_id="pair-1"):
    return PairwiseItem(
        pair_id=pair_id,
        prompt="Solve the task.",
        candidate_a={"answer": "better"},
        candidate_b={"answer": "worse"},
        reference={"answer": "better"},
    )


def test_pairwise_result_maps_blind_display_back_to_original_label():
    pair = item()
    client = FakePairwiseClient([json.dumps({"winner": "A", "rationale": "more correct"})])
    result = PairwiseJudge(client, seed=7).evaluate(pair)

    assert result.winner == ("a" if _display_order(pair.pair_id, 7) else "b")
    assert "candidate_a" not in client.messages[0][0][1]["content"]
    assert result.display_a_was_original == _display_order(pair.pair_id, 7)


def test_pairwise_report_calculates_tie_adjusted_rate_and_ci():
    client = FakePairwiseClient(
        [
            {"winner": "A", "rationale": "a"},
            {"winner": "B", "rationale": "b"},
            {"winner": "tie", "rationale": "equal"},
        ]
    )
    judge = PairwiseJudge(client, seed=0)
    report = judge.evaluate_batch([item("1"), item("2"), item("3")])

    assert report.total_pairs == 3
    assert report.ties == 1
    assert report.a_win_rate + report.b_win_rate == 1.0
    assert report.decisive_a_win_rate is not None
    assert report.decisive_a_win_rate_ci95 is not None
