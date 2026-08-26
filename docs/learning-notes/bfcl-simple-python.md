---
schema: bubblevan/v1
id: hi-agent-bfcl-simple-python-eval
content_kind: learning-note
title: "Hi-Agent BFCL simple_python 评测复盘"
date: 2026-08-25
updated: 2026-08-25
status: draft
visibility: public
summary: "从 BFCL 数据安装、原始 tool call 捕获、官方 AST checker 到可复现报告，完成 Hi-Agent 的第一个函数调用评测闭环。"
topics: [Agent, BFCL, Function Calling, Evaluation, Python]
projects: [hi-agent]
aliases: []
authors: [bubblevan]
---

这次不是先实现一个更复杂的 Agent，而是先回答一个更基础的问题：

> Hi-Agent 能不能在标准函数调用数据上，稳定地产生正确的函数名和参数？

我选择 BFCL v4 的 `simple_python`，先把评测链路缩小到单轮、单函数调用，再决定是否扩展到 `multiple`、`parallel` 和 `irrelevance`。

## 1. 先把环境边界弄清楚

BFCL 官方仓库被放在：

```text
evals/llm_evals/temp_gorilla/berkeley-function-call-leaderboard/
```

最初直接使用 Conda `base` 环境安装时，`pip` 使用了 Python 3.13，并尝试从源码编译 `numpy==1.26.4`。Windows 环境没有可用的 C/C++ 编译器，于是安装失败。

后来使用 D 盘上的独立 BFCL `.venv`，验证结果为：

```text
Python: .../berkeley-function-call-leaderboard/.venv/Scripts/python.exe
NumPy: 1.26.4
bfcl_eval: .../berkeley-function-call-leaderboard/bfcl_eval/__init__.py
```

这一步的经验是：评测依赖本身也是系统的一部分。不能只记录“安装成功”，还要记录实际解释器、关键依赖版本和包的来源路径。

## 2. BFCL 数据契约不是一个简单字符串

`BFCL_v4_simple_python.json` 中的一条样本大致包含：

```text
id
question: 按 turn 包裹的对话消息列表
function: 当前样本可用的函数描述
```

标准答案不在同一个文件的 `ground_truth` 字段里，而是在：

```text
bfcl_eval/data/possible_answer/BFCL_v4_simple_python.json
```

因此 Runner 必须使用 `id` 对齐 prompt 和 possible answer，并检查两边的数量一致。`simple_python` 当前只有一轮，所以 Provider payload 使用 `question[0]`，而不是把外层 turn 列表直接传给 API。这里不能把文档里的简化示例直接当成当前 BFCL v4 的实际数据结构。

## 3. 为什么没有直接调用 `MyFunctionCallAgent.run`

当前 `MyFunctionCallAgent` 的生产路径是：

```text
模型响应
  → 读取 tool_calls
  → 执行工具
  → 把 tool 结果发回模型
  → 返回最终自然语言
```

但 BFCL simple_python 需要评估的是：

```text
模型响应
  → 函数名
  → 参数 JSON
```

如果直接调用 `run()`，原始 `tool_calls` 已经被隐藏，最后得到的自然语言也不能可靠地反推出模型最初选择了什么函数。因此本次 Runner 直接复用了 `MyLLMClient` 的 OpenAI-compatible client，但在第一次模型响应处截取 `message.tool_calls`。

这不是绕过 Agent，而是先把“函数调用选择能力”与“工具执行循环”拆开测量。否则工具执行成功可能掩盖函数名或参数错误。

## 4. Provider schema 与 BFCL schema 之间还有一层转换

BFCL 的函数描述使用类似：

```json
{"type": "dict"}
```

而 OpenAI-compatible tools 通常期待 JSON Schema 的：

```json
{"type": "object"}
```

此外，BFCL 中可能出现 `math.factorial` 这样的函数名，而很多 Provider 不允许函数名包含点号。因此 Runner 在发送给 Provider 前把它变成 `math_factorial`，评分时使用 BFCL 的 FC profile 处理同样的名称约定。

这说明数据集格式、Provider payload 格式和评分器输入格式不是同一个接口，应该把转换写成显式边界，而不是散落在请求代码里。

## 5. Runner 的职责

`evals/llm_evals/bfcl_simple_python.py` 当前做四件事：

1. 读取 BFCL prompt 和 possible answer；
2. 为每个样本构造当前样本的 tools；
3. 保存原始 tool call 为 BFCL JSONL 结果；
4. 调用 BFCL 官方 `ast_checker`，生成逐样本报告。

默认只跑 5 条样本，`--samples 0` 才跑完整 `simple_python`。结果分成两份：

```text
result/.../BFCL_v4_simple_python_result.json  # 官方结果格式
artifacts/bfcl-simple-python.json              # 带延迟、usage、错误和预测的本地报告
```

这和 Context Eval 的经验一致：结果文件负责机器消费，报告 artifact 负责解释失败和复盘。

## 6. 当前评测能证明什么

如果 5 条样本全部通过，它只能说明：

- 当前模型能在这些样本上输出可解析的函数调用；
- 函数名和必需参数满足 BFCL checker；
- 当前 Provider payload 能被模型接受；
- Runner 能把预测、评分和运行元数据保存下来。

它不能证明：

- Agent 已经支持复杂多工具规划；
- `multiple` 和 `parallel` 一定正确；
- 工具执行结果和多轮状态管理正确；
- 对全部 BFCL v4 或真实生产任务都可靠；
- 这次准确率可以代表模型的普遍能力。

因此当前结果应被称为 smoke/regression evaluation，而不是完整能力结论。

## 7. 运行方式

在 `hi-agent` 根目录执行，使用 BFCL 的独立解释器：

```powershell
$bfclRoot = "D:\MyLab\hi-agent\evals\llm_evals\temp_gorilla\berkeley-function-call-leaderboard"
$env:BFCL_PROJECT_ROOT = $bfclRoot
$env:PYTHONPATH = "D:\MyLab\hi-agent"

& "$bfclRoot\.venv\Scripts\python.exe" `
  "D:\MyLab\hi-agent\evals\llm_evals\bfcl_simple_python.py" `
  --samples 5 `
  --temperature 0 `
  --max-tokens 256
```

真实评测前应确认 `.env` 中的 API 配置、模型是否支持原生 tools，以及这次调用是否会产生费用。

## 8. 下一步实验

我会按以下顺序推进：

```text
5 条 simple_python
  → 20 条 simple_python
  → 全量 simple_python
  → multiple
  → parallel
  → irrelevance
```

每一步都保留失败样本，而不是只记录一个总准确率。下一轮最值得观察的字段是：

- wrong function name；
- missing required parameter；
- unexpected parameter；
- invalid JSON arguments；
- provider error；
- finish reason 是否为 `length`；
- latency 与 token usage 是否出现异常。

真正进入复杂类别前，先让 `simple_python` 的结果文件和报告结构稳定下来。这样后续失败才更可能来自 Agent 能力，而不是数据读取、函数名转换或评分适配错误。
