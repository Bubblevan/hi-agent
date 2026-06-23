# test_function_call_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient
from core.config import Config
from tools.registry import MyToolRegistry
from tools.builtin.search import SearchTool
from tools.builtin.calculator import CalculatorTool
from agents.functioncall_agent import MyFunctionCallAgent

load_dotenv(find_dotenv())

print("=" * 60)
print("🧪 测试 FunctionCall Agent (原生函数调用)")
print("=" * 60)

# 1. 创建 LLM 客户端
llm = MyLLMClient()

# 2. 创建工具注册表
registry = MyToolRegistry()
search_tool = SearchTool()
calculator_tool = CalculatorTool()
registry.register_tool(search_tool)
registry.register_tool(calculator_tool)

print(f"\n✅ 已注册工具: {registry.list_tools()}\n")

# 3. 创建 FunctionCall Agent
agent = MyFunctionCallAgent(
    name="函数调用助手",
    llm=llm,
    tool_registry=registry,
    system_prompt="你是一个智能助手，可以调用工具来获取信息或进行计算。",
    max_iterations=3,
    config=Config.from_env()
)

# 测试案例 1: 数学计算（DeepSeek 原生支持 function calling）
print("\n" + "=" * 60)
print("📌 测试 1: 数学计算")
print("=" * 60)
question1 = "请帮我计算 (25 + 15) * 3 - 40 的结果。"
print(f"用户: {question1}")
answer1 = agent.run(question1)
print(f"\n助手: {answer1}")

# 测试案例 2: 搜索 + 计算混合
print("\n" + "=" * 60)
print("📌 测试 2: 搜索 + 计算")
print("=" * 60)
agent.clear_history()  # 清空历史
question2 = "请查找 2024 年诺贝尔物理学奖得主的姓名，然后告诉我他们的名字一共有几个字母。"
print(f"用户: {question2}")
answer2 = agent.run(question2)
print(f"\n助手: {answer2}")