# Hi-Agent Context Engineering Baseline

这是上下文工程改造开始前冻结的 v0 基线。数字来自改造前的测试与评测记录；没有记录的指标明确写为 `not_recorded`，不使用估算值补齐。

## 版本信息

| 字段 | 值 |
| --- | --- |
| eval_version | `context-baseline-v0` |
| git_commit | `not_recorded` |
| model | `not_recorded` |
| embedding_model | `not_recorded` |
| recorded_at | `2026-08-22` |

## 汇总

| 层次 | 结果 | 解释 |
| --- | --- | --- |
| Unit tests | `137 passed, 1 skipped` | 当前代码契约的回归基线；需保留 skipped 原因 |
| Memory eval | 71 queries：48 positive、23 abstention | 同时覆盖召回和拒答 |
| Memory threshold comparison | Recall@5：`0.9375 → 0.8542`；abstention recall：`0 → 0.3043` | `0.35` 阈值提高拒答能力，但牺牲部分正例召回 |
| Memory other metrics | Recall、MRR、nDCG、abstention、leakage、latency 均有计算 | 本文件只记录已确认的汇总数，完整 report 另行保存 |
| RAG smoke eval | 2 questions；answer success `2/2`；retrieval coverage `2/2`；answer coverage `2/2`；citation validity `2/2` | 证明端到端契约通过，不代表泛化质量 100% |
| Service cost | `not_recorded` | 未记录，不虚构 |
| Average input tokens | `not_recorded` | 下一轮真实评测必须记录 |

## RAG smoke cases

| case_id | source | result |
| --- | --- | --- |
| `pdf-yolov8-bfds` | Hello-Agents sample paper | expected terms retrieved and covered; citation valid |
| `blog-vibe-coding-layers` | Bubblevan Vibe Coding blog | expected terms retrieved and covered; citation valid |

## 解释边界

当前 RAG 评测检查的是：

- 期望术语是否出现在召回上下文；
- 期望术语是否出现在回答；
- 引用编号是否指向当前上下文。

当前 RAG 评测尚未充分覆盖：

- 答案完整性；
- 事实一致性；
- 多次运行稳定性；
- 复杂跨文档推理；
- 输入 token、输出 token、延迟和服务成本。
