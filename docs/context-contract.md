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

## 10. Message Structure V1 契约

Message Structure 将 CompiledContext 转换为稳定、可追踪的内部消息序列。

### 10.1 边界

ContextMessage 是 provider-neutral 的内部领域对象，
不是可直接传给 OpenAI、Anthropic 或 DashScope API 的请求消息。

`kind` 表示上下文内容类型，不等同于模型消息的 `role`。
role 映射由后续 Provider Formatter 负责。

### 10.2 转换规则

1. 一个 selected ContextItem 对应一个 ContextMessage。
2. 严格保持 selected_items 的顺序，不按 kind 重新排序。
3. 不合并多个同类 item。
4. ContextMessage 保留 item_id、kind、source 和 content。
5. content 必须保持原样，不能加入追踪前缀。
6. dropped_items 不得出现在输出中。
7. selected_items 为空时返回空列表。
8. 相同输入必须产生相同输出。

### 10.3 非目标

V1 不处理：

- provider role 映射；
- tool_call_id；
- OpenAI/Anthropic/DashScope 消息格式；
- 多个 item 合并；
- prompt 模板；
- 消息序列化后的 token 重算；
- LLM 调用。

## 11. ContextTrace V1 契约

ContextTrace 用于记录一次 Context Compiler 的确定性决策结果。

它只负责观测和记录，不参与预算计算、项目选择或消息转换。

### 11.1 输入

Trace Builder 接收一个已经通过校验的 `CompiledContext`：

```python
build_context_trace(compiled: CompiledContext) -> ContextTrace
```

### 11.2 输出字段

| 字段 | 含义 |
|------|------|
| `stage` | 产生该 Trace 的阶段，V1 固定为 `"compiler"` |
| `selected_item_ids` | 被选中项目的 ID，保持 `selected_items` 顺序 |
| `dropped_item_ids` | 被淘汰项目的 ID，保持 `dropped_items` 顺序 |
| `total_input_tokens` | 复制自 `CompiledContext.total_input_tokens` |
| `available_input_tokens` | 复制自 `CompiledContext.available_input_tokens` |

### 11.3 行为规则

1. `selected_item_ids` 必须与 `selected_items` 一一对应并保持顺序。
2. `dropped_item_ids` 必须与 `dropped_items` 一一对应并保持顺序。
3. token 统计直接复制自 `CompiledContext`，不重新计算预算。
4. `stage` 在 V1 中固定为 `"compiler"`。
5. Trace 不得修改传入的 `CompiledContext`。
6. 相同 `CompiledContext` 必须产生相等的 Trace。
7. Trace 不保存 item content。

### 11.4 非目标

ContextTrace V1 不处理：

- 时间戳；
- 随机 trace ID；
- 日志输出；
- JSON 持久化；
- OpenTelemetry；
- Provider 请求或响应；
- LLM latency；
- ContextMessage 内容；
- RAG、Memory 或工具调用追踪。

## 12. OpenAI-Compatible Formatter V1 契约

Formatter 将 provider-neutral 的 `ContextMessage` 转换为带 Provider role
的 `FormattedMessage`。

Formatter 只负责角色映射和追踪字段传递，不执行网络请求。

### 12.1 输入

```python
format_openai_messages(
    messages: list[ContextMessage],
) -> list[FormattedMessage]
````

### 12.2 输出字段

| 字段        | 含义                     |
| --------- | ---------------------- |
| `role`    | OpenAI-compatible 消息角色 |
| `content` | 原始消息正文，不允许修改           |
| `item_id` | 对应 ContextItem 的稳定 ID  |
| `source`  | 上下文来源                  |

`item_id` 和 `source` 属于旁路追踪字段。真正生成 Provider 请求时，
只能向 API 发送 `role` 和 `content`，不能把追踪字段写入正文。

### 12.3 kind 到 role 的映射

| kind        | role        |
| ----------- | ----------- |
| `system`    | `system`    |
| `task`      | `user`      |
| `user`      | `user`      |
| `assistant` | `assistant` |
| `retrieval` | `user`      |

以下 kind 在 V1 中必须显式失败：

* `conversation`：没有携带原始对话角色；
* `tool_result`：缺少 `tool_call_id`；
* 其他未知 kind。

### 12.4 行为规则

1. 每个 ContextMessage 对应一个 FormattedMessage。
2. 输出顺序必须与输入顺序一致。
3. content 必须保持原样。
4. item_id 和 source 必须保持原样。
5. 不合并消息。
6. 不在 content 中添加追踪前缀。
7. 不支持的 kind 必须抛出 ValueError。
8. 空输入返回空列表。
9. 相同输入必须产生相同输出。

### 12.5 非目标

Formatter V1 不处理：

* LLM 网络请求；
  -流式输出；
* Provider 响应；
* 原生工具调用；
* tool_call_id；
* JSON 日志；
* token 重新计算；
* RAG 或 Memory 查询；
* system message 合并。