# 第四章与第七章学习记录

这份笔记是我的主学习日志。顺序沿用 HelloAgents 的渐进路线：先理解第四章的 ReAct、Plan-and-Solve、Reflection，再把这些范式放进第七章的统一 Agent、消息、配置和工具接口中。

## 2026-08-22：把章节示例变成可重复的单元测试

### 本次目标

理解“示例脚本”和“单元测试”的区别：示例脚本展示完整流程，单元测试则把外部依赖替换成确定的假对象，只验证一个模块的行为和接口。

### 我的实现

- 用 `FakeLLM` 固定 `invoke` 和流式响应序列，不调用真实模型。
- 用 `tmp_path` 隔离 SQLite 数据库，避免测试修改项目根目录。
- 将第四章范式的关键轨迹分别验证为：`Thought → Action → Observation`、规划列表解析、反思提前停止。
- 将第七章的消息、配置、Agent 基类、工具注册表和工具调用迁移到 pytest。

### 验证证据

- [核心接口测试](../../tests/unit/learning/test_chapter7_core.py)
- [工具与 SimpleAgent 测试](../../tests/unit/learning/test_chapter7_tools.py)
- [经典范式测试](../../tests/unit/learning/test_chapter4_patterns.py)
- [记忆示例测试](../../tests/unit/learning/test_memory_learning_examples.py)

### 疑问与失败

这里仍需要继续理解：Function Calling 的 `tool_calls` 响应对象为什么必须同时满足 OpenAI SDK 的消息结构和工具参数结构？下一次可以增加一个带工具调用的假响应来观察完整消息轨迹。

### 下一步实验

为 ReAct 增加一个“工具不存在”的测试，观察 Agent 如何记录 Observation，并比较它与“解析失败”时的行为。
