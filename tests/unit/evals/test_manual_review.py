import json

from evals.data_generation.manual_review import ReviewSession, load_queue


def test_review_state_is_resumable_and_exports_decisions(tmp_path):
    queue_path = tmp_path / "queue.jsonl"
    queue_path.write_text(
        json.dumps({"candidate_index": 1, "candidate": {"x": 1}, "errors": ["check"]}) + "\n"
        + json.dumps({"item_id": "case-2", "candidate": {"x": 2}, "errors": []}) + "\n",
        encoding="utf-8",
    )
    state_path = tmp_path / "state.jsonl"

    session = ReviewSession(load_queue(queue_path), state_path)
    session.decide("1", "accept", reviewer="tester")
    resumed = ReviewSession(load_queue(queue_path), state_path)

    assert [row["review_id"] for row in resumed.pending()] == ["case-2"]
    resumed.decide("case-2", "reject", note="not enough evidence")
    counts = resumed.export(
        accepted=tmp_path / "accepted.jsonl",
        rejected=tmp_path / "rejected.jsonl",
        pending=tmp_path / "pending.jsonl",
    )

    assert counts == {"accepted": 1, "rejected": 1, "pending": 0}
    assert json.loads((tmp_path / "accepted.jsonl").read_text()) == {"x": 1}
    rejected = json.loads((tmp_path / "rejected.jsonl").read_text())
    assert rejected["note"] == "not enough evidence"


def test_interactive_edit_accepts_replacement(tmp_path):
    queue = [{"review_id": "a", "candidate": {"answer": 1}, "errors": ["wrong"]}]
    session = ReviewSession(queue, tmp_path / "state.jsonl")
    answers = iter(["e", '{"answer": 42}'])

    status = session.run_interactive(input_fn=lambda _: next(answers), output_fn=lambda _: None)

    assert status == "complete"
    assert session.rows[0]["decision"] == "accept"
    assert session.rows[0]["candidate"] == {"answer": 42}
