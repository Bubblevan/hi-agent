from types import SimpleNamespace

from agents.functioncall_agent import MyFunctionCallAgent
from agents.plan_solve_agent import MyPlanAndSolveAgent
from agents.react_agent import MyReActAgent
from agents.reflection_agent import MyReflectionAgent
from core.config import Config
from tools.builtin.calculator import CalculatorTool
from tools.registry import MyToolRegistry

from .fakes import FakeLLM


def calculator_registry():
    registry = MyToolRegistry()
    registry.register_tool(CalculatorTool())
    return registry


def test_react_follows_thought_action_observation_cycle():
    llm = FakeLLM(
        [
            "Thought: I need arithmetic.\nAction: calculator[2 + 3]",
            "Thought: The tool answered.\nAction: Finish[5]",
        ]
    )
    agent = MyReActAgent("react", llm, calculator_registry(), max_steps=3)

    assert agent.run("what is 2 + 3?") == "5"
    assert any("计算结果: 5" in item for item in agent.react_history)
    assert len(agent.get_history()) == 2


def test_plan_and_solve_parses_plan_and_merges_step_results():
    llm = FakeLLM(["```python\n['step one', 'step two']\n```", "result one", "result two"])
    agent = MyPlanAndSolveAgent(
        "planner",
        llm,
        tool_registry=None,
        config=Config(max_history_length=10),
    )

    answer = agent.run("solve it")

    assert "步骤 1 (step one):" in answer
    assert "result two" in answer


def test_reflection_can_stop_when_feedback_says_no_change():
    llm = FakeLLM(["draft", "无需改进"])
    agent = MyReflectionAgent("reflector", llm, max_refinement_rounds=2)

    assert agent.run("write a draft") == "draft"
    assert len(llm.invocations) == 2


def test_function_call_agent_builds_openai_tool_schema_and_returns_final_answer():
    class FakeCompletions:
        def create(self, **kwargs):
            message = SimpleNamespace(
                content="final answer",
                tool_calls=None,
                model_dump=lambda: {"role": "assistant", "content": "final answer"},
            )
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    llm = FakeLLM([])
    llm._client = fake_client
    agent = MyFunctionCallAgent("function-caller", llm, calculator_registry())

    assert agent.has_tools() is True
    assert agent.tool_schemas[0]["function"]["name"] == "calculator"
    assert agent.run("answer") == "final answer"
