# Context Bench v1

`tests/fixtures/context_cases.jsonl` 是面向上下文工程（Context Engineering）工作的**首个确定性基准测试**。

它有意与 RAG 基准区分开。RAG 测试用例考察的是证据能否被检索和引用；而上下文测试用例考察的是：在经历选择、清理、检查点（checkpoint）或压缩（compaction）之后，智能体（Agent）能否保留继续执行任务所必需的信息。

## 用例契约

每个用例包含：

- `task`：智能体需要继续执行的任务；
- `must_include`：不能丢弃的逻辑上下文片段；
- `must_exclude`：不应占据活动上下文的陈旧或重复材料；
- `required_facts_after_compaction`：必须在压缩后保留的事实；
- `allowed_to_clear`：可以移除或替换为引用的信息；
- `next_action`：在高层面上预期的延续动作。

## 当前范围

六个用例覆盖：

1. 目标保持；
2. 决策与失败记录保持；
3. 可重放的工具结果清理；
4. 记忆（Memory）/ RAG 去重；
5. 检查点恢复；
6. 前缀稳定性（用于缓存友好的上下文构建）。

这些用例目前尚未构成对真实 LLM 的评分体系。它们是确定性单元测试和集成测试的“黄金契约”。后续评估器可以在此固定格式之上，继续引入模型输出、任务成功率、令牌用量、延迟以及重复运行方差等维度，而无需改动当前的数据格式。

## RAG 微型基准（RAG Mini-Bench）

`tests/fixtures/rag_eval_cases.jsonl` 包含首个扩展后的 RAG 集合：

- 7 个 Hello-Agents PDF 正例；
- 1 个已有的 Bubblevan 博客用例；
- 2 个明确的弃权（abstention）用例。

现有的两个线上用例仍保留为冒烟测试集（smoke set）。扩展后的集合属于独立的**计费评估（cost-bearing evaluation）**，仅在显式启用时才会运行。