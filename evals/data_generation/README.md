# Generated-data quality workflow

这里的组件分成三层：生成器提出候选，确定性校验器检查硬约束，人工审核或 LLM Judge 处理仍然需要判断的质量问题。

## 1. 人工审核闭环

任何 JSONL 审核队列都可以接入。每行至少包含 `candidate` 和 `errors`，推荐提供稳定的 `review_id`：

```json
{"review_id":"aime-001","candidate":{"answer":42},"errors":["请核对数学正确性"]}
```

启动审核：

```powershell
uv run python -m evals.data_generation.manual_review review `
  --queue artifacts/aime-review.jsonl `
  --state artifacts/aime-review.state.jsonl `
  --reviewer bubblevan `
  --accepted-output artifacts/aime-reviewed.accepted.jsonl `
  --rejected-output artifacts/aime-reviewed.rejected.jsonl `
  --pending-output artifacts/aime-reviewed.pending.jsonl
```

审核过程中每条记录都可以接受、拒绝、编辑后接受、跳过或退出。每次决定立即写入 `--state`，重新运行同一命令即可继续。

已有状态只导出、不启动交互：

```powershell
uv run python -m evals.data_generation.manual_review export `
  --state artifacts/aime-review.state.jsonl `
  --accepted-output artifacts/aime-reviewed.accepted.jsonl `
  --rejected-output artifacts/aime-reviewed.rejected.jsonl `
  --pending-output artifacts/aime-reviewed.pending.jsonl
```

人工接受不等于最终冻结。导出后仍需重新跑对应的 RAG、Context 或 AIME 确定性 validator。

## 2. Pairwise Win Rate

输入 JSONL：

```json
{"pair_id":"case-001","prompt":"Solve the task","candidate_a":{"answer":"..."},"candidate_b":{"answer":"..."},"reference":{"answer":"..."},"metadata":{"suite":"aime"}}
```

运行：

```powershell
uv run python -m evals.data_generation.pairwise_judge `
  --input artifacts/pairs.jsonl `
  --output artifacts/pairwise-results.jsonl `
  --report artifacts/pairwise-report.json `
  --model deepseek-v4-flash `
  --temperature 0 `
  --seed 17
```

展示顺序按 `seed + pair_id` 稳定打乱，报告同时给出 A/B 胜场、平局、平局折半后的 Win Rate，以及排除平局后的 Wilson 95% 区间。

## 3. AIME Generator

先让模型生成候选，并把结构错误、越界答案和重复题放入审核队列：

```powershell
uv run python -m evals.data_generation.aime_generator `
  --topic algebra `
  --topic geometry `
  --count-per-topic 5 `
  --difficulty medium `
  --output artifacts/aime.accepted.jsonl `
  --review-output artifacts/aime-review.jsonl `
  --model deepseek-v4-flash `
  --temperature 0.4
```

离线重跑解析和校验，不消耗 LLM 调用：

```powershell
uv run python -m evals.data_generation.aime_generator `
  --topic algebra `
  --response artifacts/aime-raw-response.txt `
  --output artifacts/aime.accepted.jsonl `
  --review-output artifacts/aime-review.jsonl
```

AIME Generator 只保证题面、解答、答案字段和 `0..999` 范围等结构约束；它不会把模型声称的答案当成数学证明。审核完成后，建议把接受项交给独立解题器、人工复核或精确答案 evaluator，再冻结为评测集。
