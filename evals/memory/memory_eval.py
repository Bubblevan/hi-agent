from __future__ import annotations

import argparse
import io
import json
import math
import statistics
import tempfile
import time
import sys
from contextlib import contextmanager
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class RetrievalExample:
    case_id: str
    user_id: str
    query: str
    memory_types: list[str]
    gold_ids: list[str] = field(default_factory=list)
    should_abstain: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    name: str
    metrics: dict[str, float]
    examples_count: int
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metrics": self.metrics,
            "examples_count": self.examples_count,
            "failures": self.failures,
        }


class DeterministicFakeEmbedder:
    """Deterministic local embedder for evals without external API calls."""

    dimension = 16

    def encode(self, texts: str | Iterable[str]) -> list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> list[float]:
        buckets = [0.0] * self.dimension
        for index, ch in enumerate((text or "").lower()):
            buckets[(ord(ch) + index) % self.dimension] += 1.0
        norm = math.sqrt(sum(value * value for value in buckets)) or 1.0
        return [value / norm for value in buckets]


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    with source.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def build_retrieval_examples(cases: list[dict[str, Any]]) -> list[RetrievalExample]:
    examples: list[RetrievalExample] = []
    for case in cases:
        if "events" in case:
            examples.append(
                RetrievalExample(
                    case_id=case["case_id"],
                    user_id=case["user_id"],
                    query=case["query"],
                    memory_types=case.get("memory_types", ["working", "episodic", "semantic"]),
                    gold_ids=case.get("gold_memory_ids", []),
                    should_abstain=case.get("should_abstain", False),
                    tags=case.get("tags", []),
                )
            )
            continue

        memory_type = case["memory_type"]
        for index, query in enumerate(case.get("positive_queries", [])):
            examples.append(
                RetrievalExample(
                    case_id=f"{case['case_id']}:pos:{index}",
                    user_id=case["user_id"],
                    query=query,
                    memory_types=[memory_type],
                    gold_ids=[case["case_id"]],
                    tags=case.get("metadata", {}).get("tags", []),
                )
            )
        for index, query in enumerate(case.get("negative_queries", [])):
            examples.append(
                RetrievalExample(
                    case_id=f"{case['case_id']}:neg:{index}",
                    user_id=case["user_id"],
                    query=query,
                    memory_types=[memory_type],
                    should_abstain=True,
                    tags=case.get("metadata", {}).get("tags", []),
                )
            )
    return examples


@contextmanager
def patched_embedder(enabled: bool = True):
    if not enabled:
        yield
        return

    import memory.manager as manager_module

    original = manager_module.get_text_embedder
    manager_module.get_text_embedder = lambda: DeterministicFakeEmbedder()
    try:
        yield
    finally:
        manager_module.get_text_embedder = original


def build_manager(config: Any, user_id: str):
    from memory.manager import MemoryManager

    return MemoryManager(
        config=config,
        user_id=user_id,
        enable_working=True,
        enable_episodic=True,
        enable_semantic=True,
        enable_perceptual=False,
    )


def seed_memory_cases(
    cases: list[dict[str, Any]],
    manager_factory: Callable[[str], Any],
) -> dict[str, str]:
    inserted: dict[str, str] = {}
    managers: dict[str, Any] = {}

    def manager_for(user_id: str):
        if user_id not in managers:
            managers[user_id] = manager_factory(user_id)
        return managers[user_id]

    for case in cases:
        manager = manager_for(case["user_id"])
        if "events" in case:
            for index, event in enumerate(case["events"]):
                eval_id = event.get("id") or f"{case['case_id']}:event:{index}"
                memory_type = event.get("memory_type", case.get("memory_type", "episodic"))
                memory_id = manager.add_memory(
                    content=event["content"],
                    memory_type=memory_type,
                    importance=event.get("importance", case.get("importance", 0.7)),
                    metadata={
                        **event.get("metadata", {}),
                        "case_id": eval_id,
                        "parent_case_id": case["case_id"],
                        "session_id": event.get("session_id", "default"),
                    },
                )
                inserted[eval_id] = memory_id
            continue

        memory_type = case["memory_type"]
        if memory_type not in manager.memory_types:
            continue
        memory_id = manager.add_memory(
            content=case["content"],
            memory_type=memory_type,
            importance=case.get("importance", 0.5),
            metadata={**case.get("metadata", {}), "case_id": case["case_id"]},
        )
        inserted[case["case_id"]] = memory_id

    return inserted


def item_eval_id(item: Any) -> str | None:
    return item.metadata.get("case_id") or item.metadata.get("event_id")


def dcg(relevances: list[int]) -> float:
    return sum(rel / math.log2(index + 2) for index, rel in enumerate(relevances))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil((pct / 100.0) * len(ordered)) - 1)
    return ordered[index]


def evaluate_retrieval(
    cases: list[dict[str, Any]],
    config: Any,
    *,
    k_values: tuple[int, ...] = (1, 3, 5),
    min_relevance_score: float | None = None,
    use_fake_embedder: bool = True,
    debug: bool = False,
) -> EvalReport:
    examples = build_retrieval_examples(cases)
    managers: dict[str, Any] = {}

    def manager_factory(user_id: str):
        if user_id not in managers:
            managers[user_id] = build_manager(config, user_id)
        return managers[user_id]

    with patched_embedder(use_fake_embedder):
        seed_memory_cases(cases, manager_factory)

        positives = [example for example in examples if not example.should_abstain]
        abstentions = [example for example in examples if example.should_abstain]
        recall_hits = {k: 0 for k in k_values}
        reciprocal_ranks: list[float] = []
        ndcg_scores = {k: [] for k in k_values}
        abstain_true_predictions = 0
        abstain_predictions = 0
        leakage_queries = 0
        stale_failures = 0
        latencies_ms: list[float] = []
        failures: list[dict[str, Any]] = []
        debug_entries: list[dict[str, Any]] = []

        for example in examples:
            manager = manager_factory(example.user_id)
            started = time.perf_counter()
            results = manager.retrieve_memories(
                query=example.query,
                limit=max(k_values),
                memory_types=example.memory_types,
                min_relevance_score=min_relevance_score,
            )
            latencies_ms.append((time.perf_counter() - started) * 1000)

            # 记录 top score 与 retrieved IDs（debug 模式下输出）
            top_score = (
                results[0].metadata.get("relevance_score", 0.0)
                if results
                else 0.0
            )
            retrieved_ids = [item_eval_id(item) for item in results]
            debug_entries.append({
                "case_id": example.case_id,
                "query": example.query,
                "should_abstain": example.should_abstain,
                "top_score": round(top_score, 3),
                "retrieved_ids": retrieved_ids[:5],
            })
            if any(item.user_id != example.user_id for item in results):
                leakage_queries += 1
                failures.append({"case_id": example.case_id, "kind": "cross_user_leakage"})

            predicted_abstain = len(results) == 0
            if predicted_abstain:
                abstain_predictions += 1

            if example.should_abstain:
                if predicted_abstain:
                    abstain_true_predictions += 1
                else:
                    failures.append(
                        {
                            "case_id": example.case_id,
                            "kind": "failed_abstention",
                            "query": example.query,
                            "top_score": top_score,
                            "retrieved_ids": retrieved_ids,
                        }
                    )
                continue

            gold = set(example.gold_ids)
            first_rank = None
            for rank, retrieved_id in enumerate(retrieved_ids, start=1):
                if retrieved_id in gold:
                    first_rank = rank
                    break

            if first_rank is None:
                reciprocal_ranks.append(0.0)
                failures.append(
                    {
                        "case_id": example.case_id,
                        "kind": "false_abstention" if predicted_abstain else "miss",
                        "query": example.query,
                        "gold_ids": example.gold_ids,
                        "top_score": top_score,
                        "retrieved_ids": retrieved_ids,
                    }
                )
            else:
                reciprocal_ranks.append(1.0 / first_rank)

            for k in k_values:
                top_k = retrieved_ids[:k]
                if any(gold_id in top_k for gold_id in gold):
                    recall_hits[k] += 1
                relevances = [1 if retrieved_id in gold else 0 for retrieved_id in top_k]
                ideal = [1] * min(len(gold), k)
                ideal_dcg = dcg(ideal)
                ndcg_scores[k].append(dcg(relevances) / ideal_dcg if ideal_dcg else 0.0)

            if "temporal" in example.tags and first_rank not in (None, 1):
                stale_failures += 1

        positive_count = len(positives) or 1
        abstention_count = len(abstentions) or 1
        query_count = len(examples) or 1
        pos_scores = [entry["top_score"] for entry in debug_entries if not entry["should_abstain"]]
        neg_scores = [entry["top_score"] for entry in debug_entries if entry["should_abstain"]]
        
        if debug:
            print("=" * 60, file=sys.stderr)
            print("DEBUG: Per-example top scores", file=sys.stderr)
            print("=" * 60, file=sys.stderr)
            for entry in debug_entries:
                tag = "ABSTAIN" if entry["should_abstain"] else "POS"
                print(
                    f"[{tag}] {entry['case_id']} | top_score={entry['top_score']:.3f} | "
                    f"query=\"{entry['query']}\" | ids={entry['retrieved_ids']}",
                    file=sys.stderr,
                )
            print("=" * 60, file=sys.stderr)
            
            # 按 should_abstain 分组输出 score 分布
            if pos_scores:
                print(f"POS scores: min={min(pos_scores):.3f} max={max(pos_scores):.3f} "
                      f"mean={statistics.mean(pos_scores):.3f} median={statistics.median(pos_scores):.3f}",
                      file=sys.stderr)
            if neg_scores:
                print(f"NEG scores: min={min(neg_scores):.3f} max={max(neg_scores):.3f} "
                      f"mean={statistics.mean(neg_scores):.3f} median={statistics.median(neg_scores):.3f}",
                      file=sys.stderr)
            print(file=sys.stderr)
        
        metrics: dict[str, float] = {
            "examples": float(len(examples)),
            "positive_examples": float(len(positives)),
            "abstention_examples": float(len(abstentions)),
            "mrr": statistics.mean(reciprocal_ranks) if reciprocal_ranks else 0.0,
            "cross_user_leakage_rate": leakage_queries / query_count,
            "abstention_recall": abstain_true_predictions / abstention_count,
            "abstention_precision": (
                abstain_true_predictions / abstain_predictions
                if abstain_predictions
                else 0.0
            ),
            "stale_memory_error_rate": stale_failures / query_count,
            "p50_latency_ms": percentile(latencies_ms, 50),
            "p95_latency_ms": percentile(latencies_ms, 95),
            "positive_top_score_mean": statistics.mean(pos_scores) if pos_scores else 0.0,
            "negative_top_score_mean": statistics.mean(neg_scores) if neg_scores else 0.0,
            "positive_top_score_p50": statistics.median(pos_scores) if pos_scores else 0.0,
            "negative_top_score_p50": statistics.median(neg_scores) if neg_scores else 0.0,
        }
        for k in k_values:
            metrics[f"recall@{k}"] = recall_hits[k] / positive_count
            metrics[f"ndcg@{k}"] = statistics.mean(ndcg_scores[k]) if ndcg_scores[k] else 0.0

        return EvalReport(
            name="memory_retrieval",
            metrics=metrics,
            examples_count=len(examples),
            failures=failures,
        )


def run_fixture_eval(
    path: str | Path,
    *,
    use_fake_embedder: bool = True,
    min_relevance_score: float | None = None,
    debug: bool = False,
) -> EvalReport:
    from memory.base import MemoryConfig

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        config = MemoryConfig(
            database_path=str(Path(tmpdir) / "memory_eval.db"),
            working_memory_capacity=200,
            working_memory_ttl=60,
            qdrant_url=None,
            qdrant_api_key=None,
        )
        return evaluate_retrieval(
            load_jsonl(path),
            config,
            use_fake_embedder=use_fake_embedder,
            min_relevance_score=min_relevance_score,
            debug=debug,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Hi-Agent memory retrieval evals.")
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/memory_cases.jsonl",
        help="Path to memory eval JSONL fixture.",
    )
    parser.add_argument(
        "--real-embedder",
        action="store_true",
        help="Use configured real embedder instead of deterministic fake embedder.",
    )
    parser.add_argument(
        "--min-relevance-score",
        type=float,
        default=None,
        help="Filter retrieved memories below this fused relevance score.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Output per-example top scores and score distribution to stderr.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show memory initialization logs while running the eval.",
    )
    args = parser.parse_args()

    if args.verbose:
        report = run_fixture_eval(
            args.fixture,
            use_fake_embedder=not args.real_embedder,
            min_relevance_score=args.min_relevance_score,
            debug=args.debug,
        )
    else:
        with redirect_stdout(io.StringIO()):
            report = run_fixture_eval(
                args.fixture,
                use_fake_embedder=not args.real_embedder,
                min_relevance_score=args.min_relevance_score,
                debug=args.debug,
            )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
