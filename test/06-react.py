# test_react_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient
from core.config import Config
from tools.registry import MyToolRegistry
from tools.builtin.calculator import CalculatorTool
from agents.react_agent import MyReActAgent
from tools.builtin.search import SearchTool
load_dotenv(find_dotenv())

# 1. 创建 LLM 客户端
llm = MyLLMClient()

# 2. 创建工具注册表并注册工具
registry = MyToolRegistry()
search_tool = SearchTool()        # 自动检测 Tavily/SerpApi
calculator_tool = CalculatorTool()
registry.register_tool(search_tool)
registry.register_tool(calculator_tool)

print(f"\n✅ 已注册工具: {registry.list_tools()}\n")

# 3. 创建 ReAct Agent
react_agent = MyReActAgent(
    name="推理助手",
    llm=llm,
    tool_registry=registry,
    system_prompt="你是一个严谨的 AI 研究员，擅长通过搜索和计算来验证事实。",
    max_steps=5,  # 最多 5 步推理
    config=Config.from_env()
)

# ============================================================
# 测试案例 1: 需要搜索 + 计算的问题
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 1: 综合推理")
print("=" * 60)

question = "2024年诺贝尔物理学奖得主的年龄是多少？请搜索他们的出生年份并计算年龄（假设今天是2026年6月21日）。"
print(f"用户问题: {question}\n")

answer = react_agent.run(question)
print(f"\n🎯 最终答案:\n{answer}")

# ============================================================
# 测试案例 2: 纯搜索问题
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 2: 纯搜索问题")
print("=" * 60)

react_agent.clear_history()  # 清空历史，重新开始
react_agent.current_history = []  # 重置当前任务历史

question2 = "Python 3.12 引入了哪些重要的新特性？请列出至少 3 个。"
print(f"用户问题: {question2}\n")

answer2 = react_agent.run(question2)
print(f"\n🎯 最终答案:\n{answer2}")

# ============================================================
# 测试案例 3: 纯计算问题（不需要搜索）
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 3: 纯计算问题")
print("=" * 60)

react_agent.clear_history()
react_agent.current_history = []

question3 = "请计算 (25 + 15) * 3 - 40 的结果。"
print(f"用户问题: {question3}\n")

answer3 = react_agent.run(question3)
print(f"\n🎯 最终答案:\n{answer3}")

print("\n" + "=" * 60)
print("✅ ReAct 测试全部完成！")
print("=" * 60)

# ============================================================
# 可选：查看对话历史
# ============================================================
print("\n📜 最后一次对话历史:")
for msg in react_agent.get_history():
    print(f"  {msg}")