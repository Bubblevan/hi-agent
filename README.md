# Hi-Agent

基于 [hello-agent](https://github.com/xinyuwh/hello-agent) 的自学重写项目，从零学习 Agent 框架开发。

## 项目结构

```
hi-agent/
├── core/               # 核心模块
│   ├── llm_client.py  # LLM 客户端（支持 OpenAI、ModelScope、本地 VLLM/Ollama）
│   ├── agent_base.py  # Agent 基类，定义通用接口
│   ├── message.py     # 消息类型封装
│   └── config.py      # 全局配置
├── agents/            # Agent 实现
│   └── simple_agent.py # 简单对话 Agent
├── tools/             # 工具系统
│   ├── base.py        # 工具基类
│   ├── registry.py    # 工具注册表
│   └── calculator.py  # 示例：计算器工具
├── tests/             # pytest 测试
│   ├── unit/           # 离线单元测试
│   ├── integration/    # Fake Provider、真实 Provider 和外部服务测试
│   └── unit/evals/      # 评测实现的单元测试
├── evals/              # 评测实现和 CLI
├── docs/learning-notes/ # 个人学习过程、疑问和实验记录
├── main.py            # 主入口
└── .env               # 环境变量配置
```

## 快速开始

### 1. 创建 uv 环境并安装依赖

```bash
uv sync
```

这会在项目目录创建 `.venv`，并根据 `pyproject.toml` 和 `uv.lock` 安装依赖。
后续命令通过 `uv run` 执行，避免使用系统或 Conda base 环境：

```bash
uv run pytest
```

如果本机 uv 的默认缓存目录没有写权限，可以指定项目内缓存目录：

```bash
uv --cache-dir .uv-cache sync
uv --cache-dir .uv-cache run pytest
```

### 2. 配置环境变量

创建 `.env` 文件：

```env
# OpenAI 兼容 API（如 DeepSeek）
OPENAI_API_KEY=your-api-key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL_ID=deepseek-v4-flash

# 或 ModelScope
# MODELSCOPE_API_KEY=your-api-key
# LLM_MODEL_ID=Qwen/Qwen2.5-7B-Instruct

# 或本地 VLLM
# LLM_BASE_URL=http://localhost:8000/v1
# LLM_MODEL_ID=Qwen/Qwen1.5-0.5B-Chat
```

### 3. 运行测试

```bash
# 运行全部 pytest
uv run pytest

# 运行学习单测
uv run pytest tests/unit/learning

# 运行 Context 的真实 LLM eval（PowerShell）
$env:RUN_REAL_LLM_TESTS="1"
uv run pytest tests/integration/test_context_real_provider.py -m real_llm -s
```

## 学习路线

1. **01-client**: 理解 LLM API 调用方式（流式/非流式）
2. **02-message**: 理解消息格式和对话历史管理
3. **03-agent-base**: 理解 Agent 基类设计和状态管理
4. **04-simple-agent**: 理解工具调用和 ReAct 循环
5. **学习笔记**：从 [`docs/learning-notes/README.md`](docs/learning-notes/README.md) 开始记录目标、验证证据、疑问和下一步实验

## 测试分层

普通 `uv run pytest` 默认只运行离线测试，不会调用真实 LLM。真实 Context eval 使用 `real_llm` marker，并且要求显式设置 `RUN_REAL_LLM_TESTS=1`，避免普通开发测试意外消耗 API 配额。

```bash
# 离线测试
uv run pytest -m "not real_llm"

# 真实 Context Provider eval（PowerShell）
$env:RUN_REAL_LLM_TESTS="1"
uv run pytest tests/integration/test_context_real_provider.py -m real_llm -s
```

## 支持的模型提供商

| 提供商 | 环境变量 | 默认 Base URL |
|--------|---------|---------------|
| OpenAI | `OPENAI_API_KEY` | https://api.openai.com/v1 |
| DeepSeek 等兼容服务 | `OPENAI_API_KEY` | 通过 `LLM_BASE_URL` 指定 |
| ModelScope | `MODELSCOPE_API_KEY` | https://api-inference.modelscope.cn/v1/ |
| 本地 VLLM | - | http://localhost:8000/v1 |
| 本地 Ollama | - | http://localhost:11434/v1 |

## 许可证

MIT License

## 致谢

- 参考项目：[hello-agent](https://github.com/xinyuwh/hello-agent) by xinyuwh
