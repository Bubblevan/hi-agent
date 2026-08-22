# 旧 `test/` 脚本迁移索引

旧目录里的文件是按学习顺序运行的演示脚本，包含真实 LLM、搜索服务和项目根目录数据库。pytest 版本保留了它们的学习意图，但改为离线、可重复的断言。

| 旧脚本 | pytest 位置 | 迁移重点 |
| --- | --- | --- |
| `test/01-client.py`、`02-message.py`、`03-agent-base.py` | `tests/unit/learning/test_chapter7_core.py` | 客户端、消息、配置、抽象 Agent、历史窗口 |
| `test/04-simple-agent.py`、`05-search.py` | `tests/unit/learning/test_chapter7_tools.py` | 工具注册、计算器、无凭证搜索、SimpleAgent 工具循环和流式输出 |
| `test/06-react.py`、`07-plan-solve.py`、`08-reflection.py`、`09-function-call.py` | `tests/unit/learning/test_chapter4_patterns.py` | 三种经典范式和原生 Function Calling 的结构验证 |
| `test/10-memory.py`、`12-working-mem.py`、`14-sqlite.py` | `tests/unit/learning/test_memory_learning_examples.py` | 记忆数据模型、工作记忆、SQLite 往返 |
| `test/15-episodic.py`、`16-semantic.py`、`17-perceptual.py` | `tests/unit/learning/test_memory_learning_examples.py` | 三种记忆类型共享接口，以及 FakeEmbedder 下的离线检索 |
| `test/11-embedding.py` | 暂无可执行断言 | 该文件只有历史备注，没有实际测试行为；后续新增 embedding 学习实验时再补 |
| `test/13-memtool.py` | 现有 `tests/unit/memory/test_memory_tool.py` | MemoryTool 已有独立单测，避免重复搬运 |

运行方式：

```bash
uv run pytest tests/unit/learning
```
