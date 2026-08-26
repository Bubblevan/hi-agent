---
schema: bubblevan/v1
id: hi-agent-bfcl-v4-single-turn-eval
content_kind: learning-note
title: "Hi-Agent BFCL v4 单轮函数调用评测复盘"
date: 2026-08-26
updated: 2026-08-26
status: draft
visibility: public
summary: "从 simple_python 扩展到 multiple、parallel、irrelevance：把函数选择、并行调用和工具拒绝统一到一条可解释的评测链路中。"
topics: [Agent, BFCL, Function Calling, Evaluation, Python]
projects: [hi-agent]
aliases: []
authors: [bubblevan]
---

这次扩展的目标不是简单地把一个类别名改成四个类别名，而是验证 Agent 在四种不同决策上的行为：

```text
simple_python  →  是否能正确调用一个函数
multiple       →  是否能从多个候选函数中选对函数
parallel       →  是否能在同一轮发出多个独立调用
irrelevance    →  是否能判断这次不应该调用工具
```

我把这四类先限制在 BFCL v4 的单轮数据上，暂时不混入 multi-turn、live execution 或真实工具副作用。

## 1. 环境先成为评测契约的一部分

BFCL 仓库位于：

```text
evals/llm_evals/temp_gorilla/berkeley-function-call-leaderboard/
```

评测使用仓库内独立的 Python 3.10 `.venv`，而不是 Conda `base`。最终验证过：

```text
Python: .../berkeley-function-call-leaderboard/.venv/Scripts/python.exe
NumPy: 1.26.4
bfcl_eval: .../berkeley-function-call-leaderboard/bfcl_eval/__init__.py
```

BFCL 的 AST checker 还会间接导入 `qwen_agent`，因此补充了独立环境中的 `soundfile`。这个依赖没有安装到 `hi-agent` 的 base 环境。

这次保留下来的经验和 Context Compiler V1 一样：环境、版本和输入边界都属于系统行为，不能把它们当作运行命令之外的细节。

## 2. 四类数据的最小契约

四类数据都使用：

```text
BFCL_v4_<category>.json
```

其中 `question` 是按 turn 包裹的消息列表，单轮 Provider 请求使用 `question[0]`。函数描述来自当前样本的 `function` 字段，不能使用一个固定的全局工具表。

有 ground truth 的类别还需要读取：

```text
bfcl_eval/data/possible_answer/BFCL_v4_<category>.json
```

`irrelevance` 是例外：它没有对应的 possible answer 文件，因为官方语义不是比较参数，而是要求模型不要产生函数调用。

## 3. 从 simple_python 到复杂类别

### 3.1 simple_python：一个函数调用

模型需要返回一个函数名和一组参数。报告中保存的结果类似：

```json
[{"calculate_triangle_area": {"base": 10, "height": 5}}]
```

### 3.2 multiple：候选函数选择

`multiple` 并不等同于“必须调用多个函数”。当前 BFCL checker 的语义是：给出多个候选函数，模型需要选出正确的那个函数并填入参数。

因此这里主要测量：

- 函数名选择；
- 必需参数提取；
- 不要因为候选函数很多而同时调用无关函数。

### 3.3 parallel：同一轮多个调用

`parallel` 的样本可能要求同一个函数被调用多次，但参数不同。例如分别播放 Taylor Swift 和 Maroon 5 的歌曲。

Runner 在这一类请求中显式发送：

```text
parallel_tool_calls=True
```

并保存响应中的全部 `tool_calls`，而不是只读取第一个调用。官方 checker 会对 parallel 结果进行无序匹配，因此调用顺序本身不应成为错误来源。

### 3.4 irrelevance：判断不应调用工具

`irrelevance` 的函数描述与用户问题无关。正确行为不是“调用一个看起来最接近的函数”，而是返回空调用列表：

```json
[]
```

这使得评测指标从“调用得是否准确”扩展为“是否知道什么时候不要调用”。

## 4. 为什么没有直接调用 `MyFunctionCallAgent.run`

当前 `MyFunctionCallAgent` 的生产路径是：

```text
模型响应
  → 读取 tool_calls
  → 执行工具
  → 把 tool 结果发回模型
  → 返回最终自然语言
```

而 BFCL 单轮评测要观察的是第一次响应中的原始函数调用。如果直接调用 `run()`，工具执行和最终回答会把函数选择证据隐藏起来。

因此 Runner 复用了 `MyLLMClient` 的 OpenAI-compatible client，但在第一次响应处截取 `message.tool_calls`，暂时不执行任何 BFCL 工具。这是评测边界，不是生产 Agent 的最终执行实现。

## 5. Provider schema 与 BFCL schema 的转换

BFCL 使用的参数类型可能是：

```json
{"type": "dict"}
```

Provider tools 通常需要：

```json
{"type": "object"}
```

此外，`math.factorial`、`spotify.play` 等函数名包含点号，而 OpenAI-compatible API 往往要求函数名使用安全字符。因此发送前转换为 `math_factorial`、`spotify_play`，评分时交给 BFCL 的 FC profile 还原同一命名约定。

这层转换被集中在 Runner 中，避免 Provider payload、BFCL prompt 和评分输入互相污染。

## 6. Runner 的职责

`evals/llm_evals/bfcl_simple_python.py` 现在通过 `--category` 支持：

```text
simple_python
multiple
parallel
irrelevance
```

它负责：

1. 加载指定类别的数据；
2. 对齐 prompt 和 ground truth；
3. 构造当前样本的 tools；
4. 发送原生 function calling 请求；
5. 保存全部 raw tool calls；
6. 使用 BFCL 官方 AST checker 或 irrelevance checker 评分；
7. 输出逐样本报告、延迟、finish reason 和 token usage。

默认仍然只运行 5 条样本，`--samples 0` 才运行该类别全部样本。结果文件和报告按类别分开保存：

```text
result/.../BFCL_v4_<category>_result.json
artifacts/bfcl-<category>.json
```

这延续了 Context Compiler 复盘里的分层思路：机器消费的结果与人类解释用的报告不是同一个 artifact。

## 7. 运行方式

```powershell
$bfclRoot = "D:\MyLab\hi-agent\evals\llm_evals\temp_gorilla\berkeley-function-call-leaderboard"
$env:BFCL_PROJECT_ROOT = $bfclRoot
$env:PYTHONPATH = "D:\MyLab\hi-agent"
$python = "$bfclRoot\.venv\Scripts\python.exe"
$runner = "D:\MyLab\hi-agent\evals\llm_evals\bfcl_simple_python.py"

& $python $runner --category simple_python --samples 5 --temperature 0 --max-tokens 512
& $python $runner --category multiple --samples 5 --temperature 0 --max-tokens 512
& $python $runner --category parallel --samples 5 --temperature 0 --max-tokens 512
& $python $runner --category irrelevance --samples 5 --temperature 0 --max-tokens 512
```

真实运行前仍然需要确认模型支持原生 tools，并确认 Provider 的 `parallel_tool_calls` 参数可用。

## 8. 真实小样本结果

使用 `deepseek-v4-flash`、`temperature=0`、每类 5 条样本，当前结果为：

| 类别 | 结果 | 观察 |
| --- | ---: | --- |
| `simple_python` | 5/5 = 100% | 单函数调用闭环正常 |
| `multiple` | 5/5 = 100% | 候选函数选择在这 5 条上正确 |
| `parallel` | 4/5 = 80% | 4 条正确返回多个调用，1 条参数值不符合标准答案 |
| `irrelevance` | 5/5 = 100% | 5 条都没有产生工具调用 |

第一次扩展运行时，`float` 类型被原样发送给 Provider，导致部分请求在模型调用前被拒绝；修正为 JSON Schema 的 `number` 后，`multiple` 的 5 条样本全部通过。`parallel` 第一次还出现了 `max_tokens=256` 截断，增加到 512 后，调用数量问题消失。

`parallel_3` 仍然失败：模型返回了 `normal human hemoglobin` 和 `rat hemoglobin`，而该 BFCL 标准答案要求精确的 `normal hemoglobin` 等字符串。这是一次真实的参数值错误，不是 Runner 格式错误，也说明 BFCL 对字符串值的判断是严格的。

这组结果比单独的总准确率更有用：当前模型已经展示了并行调用和工具拒绝能力，但 parallel 的参数 grounding 仍然有可观察的失败。

## 9. 这次扩展能证明什么

如果四类少量样本都通过，可以说明当前模型和适配层至少完成了以下闭环：

- 能在单调用任务中选择函数并填写参数；
- 能在候选函数之间做基本的函数选择；
- 能在同一轮返回多个并行调用；
- 能在无关请求中拒绝调用工具；
- 能让同一个结果格式穿过四类评分路径；
- 能保存足够的逐样本证据供失败复盘。

它仍然不能证明：

- multi-turn、多步骤工具链正确；
- 工具执行结果会被正确消费；
- live 类别中的真实 API 行为正确；
- Agent 能在任意工具集合上泛化；
- 少量样本准确率可以代表 BFCL leaderboard 成绩。

满分只能说明当前测试契约没有观察到失败，不能把它写成生产可靠性结论。

## 10. 下一步与已知限制

目前仍然保留几个明确限制：

- Runner 仍是单轮评测，不支持 multi-turn；
- `multiple` 与 `parallel` 的语义依赖 BFCL 官方 checker，不执行真实工具；
- `irrelevance` 只检查是否产生调用，不评价自然语言拒答质量；
- 还没有做全量类别的稳定性、多次重复和模型对比；
- `evals/llm_evals/*` 仍被项目 `.gitignore` 忽略，脚本可运行但不会自然出现在 git status 中。

下一组实验应记录每个类别的：

```text
accuracy
wrong function name
wrong number of calls
missing required parameter
unexpected parameter
invalid JSON arguments
irrelevance false positive
provider error
finish_reason=length
latency / token usage
```

这次扩展真正完成的不是“多写了三个 if”，而是把 Agent 的函数调用能力拆成了四个可以分别失败、分别解释、分别回归的行为契约。
