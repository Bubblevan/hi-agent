# Hi-Agent Evals

`memory_eval.py` evaluates Memory retrieval behavior from JSONL fixtures. It
reports Recall@k, MRR, nDCG@k, abstention, leakage, latency, and top-score
distribution metrics.

Example:

```bash
python -m evals.memory_eval --fixture tests/fixtures/memory_cases.jsonl --min-relevance-score 0.35
python -m evals.memory_eval --fixture tests/fixtures/memory_cases.jsonl --debug
```

`agent_memory_eval.py` currently evaluates recorded traces only. It does not
execute `SimpleAgent` or call an LLM. A future `agent_memory_runner.py` can run
real agents, capture tool calls, convert them to traces, and reuse this scorer.
