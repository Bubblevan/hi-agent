from evals.agent_memory_eval import evaluate_agent_memory_traces


def test_agent_memory_trace_eval_reports_tool_call_metrics():
    traces = [
        {
            "case_id": "trace_001",
            "turns": [
                {
                    "expected_tools": ["memory.add"],
                    "actual_tools": ["memory.add"],
                },
                {
                    "expected_tools": ["memory.search"],
                    "actual_tools": ["memory.search"],
                },
                {
                    "expected_tools": [],
                    "actual_tools": ["memory.add"],
                },
            ],
        }
    ]

    report = evaluate_agent_memory_traces(traces)

    assert report.metrics["memory_write_precision"] == 0.5
    assert report.metrics["memory_write_recall"] == 1.0
    assert report.metrics["memory_search_precision"] == 1.0
    assert report.metrics["memory_search_recall"] == 1.0
    assert report.metrics["unnecessary_memory_write_rate"] == 1 / 3
    assert report.failures
