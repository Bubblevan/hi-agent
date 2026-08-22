# Context Contract V1

## 1. 目标

第一版只解决：在有限的 token 预算内，表示和选择 Agent 当前需要的上下文项。

## 2. 非目标

第一版不处理：

- RAG 检索
- Memory 查询
- KV Cache 真实命中率
- LLM 自动摘要
- 多 Agent
- 工具调用

## 3. ContextItem

| 字段 | 含义 | 第一版约束 |
|---|---|---|
| item_id | 上下文项的稳定标识 | 由调用方提供 |
| kind | 上下文项类型 | 例如 task、conversation、tool_result |
| content | 提交给模型的实际内容 | 不能为空或只包含空白 |
| source | 内容来源 | 例如 user、system、tool |
| priority | 相对优先级 | 用于预算不足时的选择 |
| required | 是否必须保留 | 必须是布尔值 |
| token_count | 估算 token 数量 | 必须大于等于 0 |
| metadata | 附加信息 | 不参与第一版选择逻辑 |

## 4. 保留、淘汰与压缩规则

- required 为 true 的项目不能被静默淘汰。
- 非 required 项目可以在预算不足时按照 priority 淘汰。
- 第一版不执行内容压缩。
- priority 只表达相对优先级，不表达检索相关性。
- relevance、freshness、embedding_score 和 compression_score 不属于第一版模型。

## 5. ContextBudget

| 字段 | 含义 | 约束 |
|---|---|---|
| soft_limit | 开始考虑清理的阈值 | 大于 0，不能超过 hard_limit |
| hard_limit | 绝对预算上限 | 必须大于 0 |
| output_reserve | 为模型输出预留的 token | output_reserve 必须大于等于 0，且严格小于 hard_limit。 |

## 6. required 溢出策略

当所有 required item 的 token_count 之和超过可用硬预算时，
系统必须显式报错，不能静默删除 required item。

静默删除任务目标、系统约束或关键事实，可能让模型继续运行，
但产生语义错误；显式失败更容易定位和恢复。