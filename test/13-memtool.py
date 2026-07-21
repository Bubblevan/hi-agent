# test/13-memory-tool.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv, find_dotenv
from tools.builtin import MemoryTool
from core.llm_client import MyLLMClient
from core.config import Config
from agents.functioncall_agent import MyFunctionCallAgent
from tools.registry import MyToolRegistry

load_dotenv(find_dotenv())
print("=" * 60)
print("🧪 测试 MemoryTool + SimpleAgent 集成")
print("=" * 60)

# 1. 创建 LLM
llm = MyLLMClient()

# 2. 创建记忆工具
memory_tool = MemoryTool(user_id="test_user", enable_working=True)

# 3. 创建工具注册表并注册
registry = MyToolRegistry()
registry.register_tool(memory_tool)

# 4. 创建 SimpleAgent（带工具）
agent = MyFunctionCallAgent(
    name="记忆助手",
    llm=llm,
    system_prompt="你是一个有记忆能力的AI助手，你可以使用 memory 工具来记住和检索信息。",
    tool_registry=registry,
    # enable_tool_calling=True,
    config=Config.from_env()
)

# 5. 测试对话
print("\n--- 测试: 记住信息 ---")
response = agent.run("你好，请记住我是一名Python开发者，我叫小明。")
print(f"助手: {response}")

print("\n--- 测试: 检索记忆（直接调用工具） ---")
result = memory_tool.execute("search", query="Python开发者", limit=3)
print(result)

print("\n--- 测试: 统计信息 ---")
result = memory_tool.execute("stats")
print(result)

print("\n🎉 MemoryTool 集成测试完成！")