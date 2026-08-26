---
schema: bubblevan/v1
id: hi-agent-gaia-2023-evaluation
content_kind: learning-note
title: "Hi-Agent GAIA 2023 Level 1 评测复盘"
date: 2026-08-26
updated: 2026-08-26
status: draft
visibility: public
summary: "按第十二章的 Dataset、Evaluator、Metrics 三层结构接入 GAIA，并复盘搜索工具、答案格式和 Agent 工具循环的真实失败。"
topics: [Agent, GAIA, Evaluation, Tool Use, Multimodal]
projects: [hi-agent]
aliases: []
authors: [bubblevan]
---

这次不是把 BFCL 的函数调用 Runner 换一个数据集路径，而是把 GAIA 处理成一个更完整的 Agent 评测闭环：

```text
Parquet 元数据 + 附件
        ↓
Dataset：加载题目、级别、附件路径
        ↓
Agent：搜索、计算、读取附件、多轮工具调用
        ↓
Evaluator：抽取 FINAL ANSWER、准精确匹配
        ↓
Metrics / Artifacts：准确率、逐题证据、JSONL、JSON 报告
```

## 1. 先确认数据契约

GAIA 数据位于：

```text
evals/llm_evals/gaia/
```

当前数据使用 `2023/validation/metadata.parquet` 和 `2023/test/metadata.parquet`，而不是第十二章示例中的旧 `metadata.jsonl`。[官方 GAIA README](https://huggingface.co/datasets/gaia-benchmark/GAIA/blob/main/README.md) 也说明了这一 Parquet 格式，并保留 `task_id`、`Question`、`Level`、`Final answer`、`file_name`、`file_path` 等字段。

本地读取结果：

```text
validation：165 条
  Level 1：53
  Level 2：86
  Level 3：26
  带附件：38

test：301 条
  Level 1：93
  Level 2：159
  Level 3：49
  带附件：71
```

Runner 对 `test` 强制不读取答案、不评分，避免把私有答案复制到本地诊断结果。实际实验先使用 validation。

## 2. 三层实现

核心实现位于：

```text
evals/llm_evals/gaia_runner.py
```

`GAIADataset` 负责：

- 读取 Parquet；
- 按 `split` 和 `level` 筛选；
- 兼容当前字段名；
- 将 `file_path` 解析为本地附件；
- 限制附件只能位于当前 split 目录内。

`GAIAAttachmentTool` 负责把附件暴露给 Agent。它复用了项目已有的 `MarkitdownLoader`，当前可处理 PDF、DOCX、PPTX、XLSX、CSV、JSON、XML、代码和部分图片。

Agent 使用项目现有的 `MyFunctionCallAgent`，注册三个工具：

```text
calculator
search
read_attachment
```

`GAIAEvaluator` 负责：

- 为每题创建新的 Agent，避免历史污染；
- 允许最多 8 轮工具调用；
- 从回答中抽取 `FINAL ANSWER`；
- 按章节描述的规则规范化数字、大小写、标点和逗号列表；
- 保存 predicted、expected、normalized value、response、latency 和错误状态。

## 3. 环境问题：不是 key，而是 SDK

第一次运行时，`.env` 中的配置实际可以被解析：

```text
TAVILY_API_KEY：存在
SERPAPI_API_KEY：存在
LLM_API_KEY：存在
LLM_BASE_URL：存在
LLM_MODEL_ID：存在
```

但 `SearchTool` 仍报告没有可用搜索源。原因是项目只配置了 key，没有安装对应 Python SDK：

```text
ModuleNotFoundError: No module named 'tavily'
ModuleNotFoundError: No module named 'serpapi'
```

随后将 `tavily-python` 加入项目依赖并安装到：

```text
D:\MyLab\hi-agent\.venv
```

修复后的验证结果：

```text
Tavily 搜索源已启用
available_backends = ['tavily']
```

SerpApi 仍然显示“未安装”，但这不是错误，因为 Tavily 已经是可用后端。GAIA 的搜索调用已经从“返回配置提示”变成真实 Tavily 搜索。

## 4. 第一次真实结果

运行配置：

```text
model：deepseek-v4-flash
temperature：0
max_tokens：4096
split：validation
level：1
samples：5
```

结果：

```text
2/5 = 40.00%
```

结果文件：

```text
D:\MyLab\hi-agent\artifacts\gaia-validation-level1-20260826T100725Z.jsonl
D:\MyLab\hi-agent\artifacts\gaia-validation-level1-20260826T100725Z.json
```

逐题失败不是同一种问题：

| 类型 | 现象 | 归因 |
| --- | --- | --- |
| 单位理解错误 | 计算结果约为 17.125 千小时，但回答为 `17000`，标准答案为 `17` | 模型把“多少千小时”回答成了“多少小时” |
| 工具协议泄漏 | 多轮搜索后最终答案变成 `</｜｜DSML｜｜tool_calls>` | Provider 特殊工具标记泄漏到文本，Runner 没有做协议层清理 |
| 空回答 | 复杂概率题返回 `（无内容）` | 模型第一轮没有产生可用文本或工具调用 |
| 正常搜索回答 | 鱼袋体积回答 `0.1777` | 搜索、答案抽取和匹配闭环正常 |
| 正常搜索回答 | 视频问题回答 `3` | 搜索和最终答案格式正常 |

这组结果说明：Tavily 接通只是基础设施成功，并不等于 GAIA Agent 成功。当前主要瓶颈已经从“没有搜索工具”转移到答案单位、工具协议兼容和复杂任务的最终回答稳定性。

## 5. 这次实验证明了什么

已经证明：

- 当前 Parquet 数据可以离线加载；
- 附件路径有明确安全边界；
- XLSX 等文档可以通过 MarkItDown 转成文本；
- Tavily 可以被 Agent 实际调用；
- Agent 可以在一题中进行多轮搜索和计算；
- Runner 可以生成 GAIA JSONL 和逐题诊断报告；
- Level 1 小样本的真实准确率可以被复现。

还不能证明：

- Level 1 全部 53 条的表现；
- Level 2/3 的综合推理能力；
- 图片理解和音频转录能力；
- Python 沙箱、浏览器和复杂文件分析能力；
- 结果可以直接代表 GAIA leaderboard 成绩；
- Agent 能稳定处理 Provider 的私有 tool-call 标记。

`2/5` 是这次配置、模型、提示词和工具集合下的观测值，不应外推成模型的通用 GAIA 能力。

## 6. 已知限制与下一步

当前仍有几个明确限制：

- 音频附件尚未接入 Whisper 或其他转录器；
- 图片目前依赖 MarkItDown 的转换能力，没有稳定的视觉输入协议；
- 没有 Python 沙箱，复杂表格和计算任务的可执行能力不足；
- 搜索结果没有统一保存引用 URL 和证据片段；
- `MyFunctionCallAgent` 没有把原始 finish reason、token usage 传回评测器；
- Provider 的 DSML 特殊标记没有被统一转换成标准 tool call；
- GAIA 的准精确匹配仍会惩罚“语义正确但单位表达不同”的答案。

下一步按这个顺序推进：

1. 在没有附件的题目中禁用 `read_attachment`，减少无意义工具调用；
2. 给 Agent 增加最终答案格式校验，处理空回答和 DSML 泄漏；
3. 将原始响应、finish reason、工具轮数和 token usage 纳入报告；
4. 补充音频转录和 Python 沙箱；
5. 先分别运行 Level 1/2/3 的 5 条 validation，再扩展到完整 validation；
6. 最后再考虑官方提交格式和模型横向对比。

这次真正完成的不是“接上一个搜索 API”，而是把 GAIA 的失败拆成了数据边界、工具可用性、Agent 循环、答案格式和评分规则几个可以分别验证的层次。
