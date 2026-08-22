# RAG Mini-Bench v1

The expanded cases live in `tests/fixtures/rag_eval_cases.jsonl`.

## Suites

| Suite | Cases | Purpose |
| --- | ---: | --- |
| smoke | 2 | Run on every explicitly enabled live RAG check |
| mini-v1 | 10 | Compare retrieval, answer coverage, citation validity, and abstention |

The mini-bench currently contains seven positive questions about the Hello-Agents PDF, one previously validated Bubblevan blog question, and two questions whose answers are intentionally absent from the PDF.

## Why the abstention cases are separate

The current RAG pipeline validates citations and expected terms, but it does not yet expose a calibrated abstention policy. The two negative cases therefore belong in the dataset now, while their strict pass/fail policy will be added when the evaluator has an explicit abstention threshold.

Do not report the negative cases as ordinary answer accuracy. Report at least:

- positive answer success;
- retrieval expected-term coverage;
- answer expected-term coverage;
- citation validity;
- abstention recall;
- false-answer rate.

## Required result metadata

Every live run should save the dataset version, model, embedding model, Git commit, case ID, answer, retrieved chunk IDs, citations, input tokens, output tokens, latency, and error information. When a provider does not expose a field, write `not_recorded`.
