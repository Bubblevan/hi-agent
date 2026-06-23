# test_plan_solve_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient
from core.config import Config
from tools.registry import MyToolRegistry
from tools.builtin.search import SearchTool
from tools.builtin.calculator import CalculatorTool
from agents.plan_solve_agent import MyPlanAndSolveAgent

load_dotenv(find_dotenv())

print("=" * 60)
print("🧪 测试 Plan-and-Solve Agent (先规划，后执行)")
print("=" * 60)

# 1. 创建 LLM 客户端
llm = MyLLMClient()

# 2. 创建工具注册表并注册工具
registry = MyToolRegistry()
search_tool = SearchTool()
calculator_tool = CalculatorTool()
registry.register_tool(search_tool)
registry.register_tool(calculator_tool)

print(f"\n✅ 已注册工具: {registry.list_tools()}\n")

# 3. 创建 PlanAndSolve Agent
agent = MyPlanAndSolveAgent(
    name="规划执行助手",
    llm=llm,
    tool_registry=registry,
    system_prompt="你是一个严谨的问题解决专家，擅长将复杂问题分解为可执行的步骤。",
    max_tool_iterations_per_step=3,
    config=Config.from_env()
)

# ============================================================
# 测试案例 1: 复杂数学 + 逻辑问题
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 1: 复杂数学计算")
print("=" * 60)

question1 = "一个水果店周一卖出了15个苹果。周二卖出的苹果数量是周一的两倍。周三卖出的数量比周二少了5个。请问这三天总共卖出了多少个苹果？"
print(f"用户问题: {question1}\n")

answer1 = agent.run(question1)
print(f"\n🎯 最终答案:\n{answer1}")

# ============================================================
# 测试案例 2: 需要搜索信息的综合问题
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 2: 需要搜索信息的问题")
print("=" * 60)

# 重置 Agent（清空历史）
agent.clear_history()

question2 = "请帮我查找 2024 年巴黎奥运会的举办日期，然后计算从 2024 年 1 月 1 日到奥运会开幕日有多少天？"
print(f"用户问题: {question2}\n")

answer2 = agent.run(question2)
print(f"\n🎯 最终答案:\n{answer2}")

# ============================================================
# 测试案例 3: 纯逻辑规划（无工具）
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 3: 纯逻辑问题（无需工具）")
print("=" * 60)

# 这里我们创建一个不使用工具的 Agent 实例
agent_no_tools = MyPlanAndSolveAgent(
    name="逻辑助手",
    llm=llm,
    tool_registry=None,  # 无工具
    system_prompt="你是一个善于分解复杂逻辑问题的助手。",
    config=Config.from_env()
)

question3 = "请规划如何从北京去上海旅游，列出需要准备的 4 个主要步骤。"
print(f"用户问题: {question3}\n")

answer3 = agent_no_tools.run(question3)
print(f"\n🎯 最终答案:\n{answer3}")

print("\n" + "=" * 60)
print("✅ Plan-and-Solve 测试全部完成！")
print("=" * 60)