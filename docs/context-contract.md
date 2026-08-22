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
| priority | 相对优先级 | **数字越大，优先级越高。** 用于预算不足时的选择 |
| required | 是否必须保留 | 必须是布尔值 |
| token_count | 估算 token 数量 | 必须大于等于 0 |
| metadata | 附加信息 | 不参与第一版选择逻辑 |

**priority 行为约定**：
- priority 数字越大，优先级越高。
- priority 相同时，保持输入顺序，不额外重排。

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
| output_reserve | 为模型输出预留的 token | output_reserve 必须大于等于 0，且严格小于 hard_limit |

## 6. required 溢出策略

当所有 required item 的 token_count 之和超过可用硬预算时，
系统必须显式报错，不能静默删除 required item。

静默删除任务目标、系统约束或关键事实，可能让模型继续运行，
但产生语义错误；显式失败更容易定位和恢复。

---

## 7. Selector V1 契约

### 7.1 预算边界定义

```
available_input = hard_limit - output_reserve
selection_target = min(soft_limit, available_input)
```

- `available_input`：输入上下文的绝对硬边界，不可突破。
- `selection_target`：Selector 正常希望压到的目标值。
- required 总量超过 `available_input`：抛出 `BudgetExceededError`。
- required 总量超过 `selection_target`、但没有超过 `available_input`：required 仍全部保留，但不再选择 optional。
- optional 只能使用 required 留下的目标预算。

示例：

```
soft_limit = 70
hard_limit = 100
output_reserve = 20

available_input = 80
selection_target = 70
```

Selector 正常最多选到 70，而不是 80。最后 20 必须留给输出，70～80 是 required 项必要时可以使用的缓冲区域。

### 7.2 Selector 算法（V1）

1. 检查 `item_id` 是否重复，重复则显式失败。
2. 调用 `assert_within_budget()`，确认 required 没突破硬预算。
3. required 项全部保留，不受 priority 影响。
4. optional 按 priority 从高到低尝试加入。
5. priority 相同时保持原输入顺序。
6. 某个 optional 放不下时跳过，继续尝试后面更小的项目。
7. 最终返回结果仍保持原始输入顺序。

**关键**：priority 决定"谁入选"，不决定最终 prompt 的排列顺序。

## 8. Selector V1 实现规则

### 8.1 priority 语义

- priority 数字越大，优先级越高。
- priority 相同时，按输入顺序作为 tie-break（先出现的优先被选择）。

### 8.2 选择算法

1. 检查 `item_id` 是否重复，重复则抛出 `ValueError`。
2. 调用 `assert_within_budget()`，确认 required 项未突破硬预算。
3. required 项全部保留，不受 priority 影响。
4. 计算 optional 可用预算：
   ```
   selection_target = min(soft_limit, available_input)
   optional_budget = max(0, selection_target - required_tokens)
   ```
5. optional 按 priority 降序尝试加入：
   - 若当前项可放入剩余预算，则选中；
   - 若放不下，跳过该项，继续尝试后续项。
6. priority 相同时，按输入顺序决定选择优先级。
7. 最终返回结果按原始输入顺序排列，不按 priority 重排。

### 8.3 关键边界

- required 项超过 `soft_limit` 但未超过 `available_input` 时，optional 全部丢弃，required 保留。
- 高 priority 的 large optional 放不下时，不阻塞后续低 priority 的 small optional。
- `output_reserve` 不参与 optional 选择计算，只影响 `available_input`。

## 9. Compiler V1 契约

### 9.1 目标

Compiler 负责将 Selector 的选择结果组织成一次完整的编译结果，并报告选择情况。

**Compiler 不做**：
- RAG 检索
- Memory 查询
- LLM 调用
- 消息格式化
- 内容压缩/摘要
- KV Cache 管理

**Compiler 只做**：
- 调用 Selector
- 组织选中的 ContextItem
- 记录被丢弃的 ContextItem
- 计算 token 统计信息
- 传递 Selector 的异常

### 9.2 输入

| 参数 | 类型 | 说明 |
|------|------|------|
| `items` | `List[ContextItem]` | 候选上下文项列表 |
| `budget` | `ContextBudget` | 上下文预算配置 |

### 9.3 输出：CompiledContext

| 字段 | 类型 | 说明 |
|------|------|------|
| `selected_items` | `List[ContextItem]` | 最终被选中的上下文项，保持输入顺序 |
| `dropped_items` | `List[ContextItem]` | 未被选中的 optional 项，保持输入顺序 |
| `total_input_tokens` | `int` | `selected_items` 的 token 总和 |
| `available_input_tokens` | `int` | 扣除 output_reserve 后的输入预算（即 `hard_limit - output_reserve`） |

### 9.4 行为规则

1. Compiler 必须调用 `select_items()`，不重新实现 priority 排序。
2. `required` 项必须保留在 `selected_items` 中。
3. 被丢弃的只能是 `optional` 项，且必须记录在 `dropped_items` 中。
4. `selected_items` 和 `dropped_items` 不应有交集。
5. `total_input_tokens` 等于 `selected_items` 的 token_count 总和。
6. `total_input_tokens` 不得超过 `available_input_tokens`。
7. Selector 抛出的 `BudgetExceededError` 和 `ValueError` 应继续向上传递，不捕获。
8. 相同输入必须得到相同输出（确定性）。