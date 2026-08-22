from core.config import Config
from tools.builtin.calculator import CalculatorTool
from tools.builtin.search import SearchTool
from tools.registry import MyToolRegistry
from agents.simple_agent import MySimpleAgent

from .fakes import FakeLLM


def test_calculator_and_registry_support_chapter_example():
    registry = MyToolRegistry()
    registry.register_tool(CalculatorTool())

    assert registry.list_tools() == ["calculator"]
    assert registry.execute_tool("calculator", "15 * 8 + 32") == "计算结果: 152"
    assert "calculator" in registry.get_tools_description()


def test_registry_supports_function_tools():
    registry = MyToolRegistry()
    registry.registry_function("uppercase", "convert text", str.upper)

    assert registry.execute_tool("uppercase", "hello") == "HELLO"
    registry.unregister("uppercase")
    assert "uppercase" not in registry.list_tools()


def test_search_tool_is_safe_without_external_credentials(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    tool = SearchTool()

    assert tool.run({"query": "anything"}).startswith("没有可用的搜索源")
    assert tool.run({"query": "  "}) == "错误: 搜索查询不能为空"


def test_simple_agent_tool_loop_and_dynamic_tool_management():
    registry = MyToolRegistry()
    calculator = CalculatorTool()
    registry.register_tool(calculator)
    llm = FakeLLM(["[TOOL_CALL:calculator:2 + 3]", "最终结果是 5"])
    agent = MySimpleAgent(
        "calculator-agent",
        llm,
        tool_registry=registry,
        config=Config(max_history_length=10),
    )

    assert agent.run("计算 2 + 3") == "最终结果是 5"
    assert len(llm.invocations) == 2
    assert agent.has_tools() is True
    assert agent.list_tools() == ["calculator"]


def test_simple_agent_streaming_collects_response_and_history():
    agent = MySimpleAgent(
        "stream-agent",
        FakeLLM([], stream_chunks=["流", "式", "回答"]),
        enable_tool_calling=False,
    )

    assert list(agent.stream_run("开始")) == ["流", "式", "回答"]
    assert [message.content for message in agent.get_history()[-2:]] == [
        "开始",
        "流式回答",
    ]
