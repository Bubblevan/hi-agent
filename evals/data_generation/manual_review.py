"""Resumable command-line human review for generated-data queues.

The queue format is deliberately generic.  A row normally looks like::

    {"review_id": "case-1", "candidate": {...}, "errors": ["..."]}

The same tool can review RAG, AIME, Context, or any future generated-data
candidate.  Decisions are persisted after every action, so an interrupted
session can resume from the same state file.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


DECISIONS = {"accept", "reject"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    rows: list[dict[str, Any]] = []
    with source.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{source}:{line_number}: invalid JSON: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"{source}:{line_number}: expected a JSON object")
            rows.append(row)
    return rows


def _write_jsonl(path: str | Path, rows: Iterable[Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    output.write_text(text, encoding="utf-8")


def _write_state(path: str | Path, rows: Iterable[dict[str, Any]]) -> None:
    """Persist state atomically enough for a Ctrl+C between review items."""

    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_name(state_path.name + ".tmp")
    _write_jsonl(temporary, rows)
    temporary.replace(state_path)


def _review_id(raw: dict[str, Any], index: int) -> str:
    for key in ("review_id", "item_id", "case_id", "candidate_index"):
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return f"review-{index}"


def load_queue(path: str | Path) -> list[dict[str, Any]]:
    """Normalize a generated-data review queue into persistent review rows."""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(_read_jsonl(path), start=1):
        review_id = _review_id(raw, index)
        if review_id in seen:
            raise ValueError(f"duplicate review_id: {review_id}")
        seen.add(review_id)
        candidate = raw.get("candidate", raw)
        errors = raw.get("errors", [])
        if not isinstance(errors, list):
            errors = [str(errors)]
        result.append(
            {
                "review_id": review_id,
                "candidate": candidate,
                "errors": [str(error) for error in errors],
                "metadata": raw.get("metadata", {}),
                "decision": "pending",
                "reviewer": "",
                "note": "",
                "updated_at": "",
            }
        )
    return result


def load_state(path: str | Path) -> list[dict[str, Any]]:
    """Load a previously persisted review state."""

    state_path = Path(path)
    if not state_path.exists():
        return []
    rows = _read_jsonl(state_path)
    for row in rows:
        if "review_id" not in row:
            raise ValueError(f"{state_path}: state row has no review_id")
    return rows


class ReviewSession:
    """A resumable review session over a generic JSONL queue."""

    def __init__(self, queue: list[dict[str, Any]], state_path: str | Path):
        self.state_path = Path(state_path)
        previous = {row["review_id"]: row for row in load_state(self.state_path)}
        self.rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in queue:
            review_id = row["review_id"]
            if review_id in seen:
                raise ValueError(f"duplicate review_id: {review_id}")
            seen.add(review_id)
            restored = dict(row)
            restored.update(previous.get(review_id, {}))
            restored["review_id"] = review_id
            self.rows.append(restored)
        for review_id, row in previous.items():
            if review_id not in seen:
                self.rows.append(row)
        self.save()

    @classmethod
    def from_state(cls, state_path: str | Path) -> "ReviewSession":
        rows = load_state(state_path)
        session = cls.__new__(cls)
        session.state_path = Path(state_path)
        session.rows = rows
        return session

    def save(self) -> None:
        _write_state(self.state_path, self.rows)

    def pending(self) -> list[dict[str, Any]]:
        return [row for row in self.rows if row.get("decision", "pending") == "pending"]

    def decide(
        self,
        review_id: str,
        decision: str,
        *,
        candidate: Any | None = None,
        note: str = "",
        reviewer: str = "",
    ) -> dict[str, Any]:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        for row in self.rows:
            if row["review_id"] == review_id:
                row["decision"] = decision
                if candidate is not None:
                    row["candidate"] = candidate
                row["note"] = note
                row["reviewer"] = reviewer
                row["updated_at"] = _timestamp()
                self.save()
                return row
        raise KeyError(f"unknown review_id: {review_id}")

    def export(
        self,
        *,
        accepted: str | Path | None = None,
        rejected: str | Path | None = None,
        pending: str | Path | None = None,
    ) -> dict[str, int]:
        accepted_rows = [row["candidate"] for row in self.rows if row.get("decision") == "accept"]
        rejected_rows = [row for row in self.rows if row.get("decision") == "reject"]
        pending_rows = [row for row in self.rows if row.get("decision", "pending") == "pending"]
        if accepted:
            _write_jsonl(accepted, accepted_rows)
        if rejected:
            _write_jsonl(rejected, rejected_rows)
        if pending:
            _write_jsonl(pending, pending_rows)
        return {
            "accepted": len(accepted_rows),
            "rejected": len(rejected_rows),
            "pending": len(pending_rows),
        }

    def run_interactive(
        self,
        *,
        reviewer: str = "",
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> str:
        """Review pending rows until completion or an explicit quit."""

        pending_ids = [row["review_id"] for row in self.pending()]
        skipped: set[str] = set()
        while True:
            current = next(
                (row for row in self.rows if row["review_id"] in pending_ids and row.get("decision", "pending") == "pending" and row["review_id"] not in skipped),
                None,
            )
            if current is None:
                return "complete" if not self.pending() else "paused"
            output_fn(f"\n[{current['review_id']}] candidate:")
            output_fn(json.dumps(current["candidate"], ensure_ascii=False, indent=2))
            if current["errors"]:
                output_fn("errors: " + "; ".join(current["errors"]))
            output_fn("[a]ccept [r]eject [e]dit [s]kip [q]uit")
            command = input_fn("> ").strip().lower()
            if command in {"q", "quit"}:
                return "paused"
            if command in {"s", "skip"}:
                skipped.add(current["review_id"])
                continue
            if command in {"a", "accept"}:
                self.decide(current["review_id"], "accept", reviewer=reviewer)
                skipped.discard(current["review_id"])
                output_fn("saved: accept")
                continue
            if command in {"r", "reject"}:
                note = input_fn("note (optional): ").strip()
                self.decide(current["review_id"], "reject", note=note, reviewer=reviewer)
                skipped.discard(current["review_id"])
                output_fn("saved: reject")
                continue
            if command in {"e", "edit"}:
                replacement = input_fn("replacement candidate as one-line JSON: ").strip()
                try:
                    edited = json.loads(replacement)
                except json.JSONDecodeError as error:
                    output_fn(f"invalid JSON, not saved: {error}")
                    continue
                self.decide(current["review_id"], "accept", candidate=edited, reviewer=reviewer)
                skipped.discard(current["review_id"])
                output_fn("saved: edited candidate accepted")
                continue
            output_fn("unknown command; nothing saved")


def _add_export_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--accepted-output", type=Path)
    parser.add_argument("--rejected-output", type=Path)
    parser.add_argument("--pending-output", type=Path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    review_parser = subparsers.add_parser("review", help="review a queue interactively")
    review_parser.add_argument("--queue", type=Path, required=True)
    review_parser.add_argument("--state", type=Path, required=True)
    review_parser.add_argument("--reviewer", default="")
    _add_export_arguments(review_parser)

    export_parser = subparsers.add_parser("export", help="export a saved review state")
    export_parser.add_argument("--state", type=Path, required=True)
    _add_export_arguments(export_parser)

    args = parser.parse_args()
    if args.command == "review":
        session = ReviewSession(load_queue(args.queue), args.state)
        status = session.run_interactive(reviewer=args.reviewer)
    else:
        session = ReviewSession.from_state(args.state)
        status = "exported"
    counts = session.export(
        accepted=args.accepted_output,
        rejected=args.rejected_output,
        pending=args.pending_output,
    )
    print(f"status={status} " + " ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
