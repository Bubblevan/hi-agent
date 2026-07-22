from evals.memory_eval import build_retrieval_examples, evaluate_retrieval


def test_memory_eval_builds_examples_from_fixture(memory_cases):
    examples = build_retrieval_examples(memory_cases)

    assert examples
    assert any(example.gold_ids for example in examples)
    assert any(example.should_abstain for example in examples)


def test_memory_retrieval_eval_reports_core_metrics(memory_config, memory_cases):
    report = evaluate_retrieval(memory_cases, memory_config)

    assert report.examples_count > 0
    assert report.metrics["cross_user_leakage_rate"] == 0.0
    assert report.metrics["recall@5"] >= 0.75
    assert "mrr" in report.metrics
    assert "ndcg@5" in report.metrics
    assert "p95_latency_ms" in report.metrics
    assert "positive_top_score_mean" in report.metrics
    assert "negative_top_score_mean" in report.metrics


def test_memory_retrieval_eval_threshold_enables_abstention(memory_config, memory_cases):
    report = evaluate_retrieval(
        memory_cases,
        memory_config,
        min_relevance_score=0.3,
    )

    assert report.metrics["abstention_recall"] > 0.0
    assert any(failure["kind"] == "failed_abstention" for failure in report.failures)
