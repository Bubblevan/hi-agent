# RAG Mini-Bench v1

The expanded cases live in `tests/fixtures/rag_eval_cases.jsonl`.  Each row is
validated by `evals.rag.schema.RAGEvalCase` and uses structured
`gold_evidence` entries with a 1-based page number and an exact quote.

## Suites

| Suite | Cases | Purpose |
| --- | ---: | --- |
| smoke | 2 | Run on every explicitly enabled live RAG check |
| mini-v1 | 10 | Compare retrieval, answer coverage, citation validity, and abstention |

The mini-bench currently contains seven positive questions about the Hello-Agents PDF, one previously validated Bubblevan blog question, and two questions whose answers are intentionally absent from the PDF.  The PDF is frozen at `tests/fixtures/sources/sample_paper.pdf`, so page references do not depend on a sibling checkout.

## Why the abstention cases are separate

The current RAG pipeline validates citations and expected terms, but it does not yet expose a calibrated abstention policy. The two negative cases therefore belong in the dataset now, while their strict pass/fail policy will be added when the evaluator has an explicit abstention threshold. `evals.rag.runner` still validates that negative cases contain no positive evidence.

Do not report the negative cases as ordinary answer accuracy. Report at least:

- positive answer success;
- retrieval expected-term coverage;
- answer expected-term coverage;
- citation validity;
- abstention recall;
- false-answer rate.

## Required result metadata

Every live run should save the dataset version, model, embedding model, Git commit, case ID, answer, retrieved chunk IDs, citations, input tokens, output tokens, latency, and error information. When a provider does not expose a field, write `not_recorded`.

## Offline validation

Run the schema, source checksum, page range, exact quote, and expected-term
checks with:

```text
python -m evals.rag.runner tests/fixtures/rag_eval_cases.jsonl tests/fixtures/rag_sources.json --project-root .
```

## Candidate generation

`evals.data_generation.rag_generator` sends one page at a time to an injected
LLM client. The response is parsed as JSONL, schema-validated, checked against
the original page text, deduplicated, and split into accepted cases plus a
review queue. Only accepted cases should be frozen into the benchmark.

For a saved response, validation is offline and does not call an API:

```text
python -m evals.data_generation.rag_generator \
  --source tests/fixtures/sources/sample_paper.pdf \
  --source-id hello-agents-sample-paper \
  --response candidates.jsonl \
  --output candidates.validated.jsonl \
  --review-output candidates.review.jsonl
```

Omitting `--response` explicitly opts into the project's `MyLLMClient` and a
real provider call.
