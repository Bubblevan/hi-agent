# 章节示例到 pytest 的迁移索引

之前按学习顺序编写的章节示例，已经迁移为 pytest 测试。pytest 版本保留了它们的学习意图，并将外部依赖拆分为离线 fake 测试和显式运行的真实 Provider eval。

| 学习主题 | pytest 位置 | 迁移重点 |
| --- | --- | --- |
| 客户端、消息、Agent 基类 | `tests/unit/learning/test_chapter7_core.py` | 客户端、消息、配置、抽象 Agent、历史窗口 |
| 工具与 SimpleAgent | `tests/unit/learning/test_chapter7_tools.py` | 工具注册、计算器、无凭证搜索、工具循环和流式输出 |
| ReAct、Plan-and-Solve、Reflection、Function Calling | `tests/unit/learning/test_chapter4_patterns.py` | 经典范式和原生 Function Calling 的结构验证 |
| 工作记忆与 SQLite | `tests/unit/learning/test_memory_learning_examples.py` | 记忆数据模型、工作记忆、SQLite 往返 |
| Episodic、Semantic、Perceptual Memory | `tests/unit/learning/test_memory_learning_examples.py` | 三种记忆类型共享接口，以及 FakeEmbedder 下的离线检索 |
| Context Fake Provider | `tests/integration/test_context_fake_provider.py` | 完整上下文链路到 Provider 边界的确定性验证 |
| Context 真实 LLM Provider | `tests/integration/test_context_real_provider.py` | 真实模型消费 context payload；使用 `real_llm` marker 和环境变量门控 |

运行方式：

```bash
# 默认离线测试
uv run pytest

# 显式运行真实 Context eval（PowerShell）
$env:RUN_REAL_LLM_TESTS="1"
uv run pytest tests/integration/test_context_real_provider.py -m real_llm -s
```
