# test_simple_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient
from core.config import Config
from tools.registry import MyToolRegistry
from tools.calculator import CalculatorTool
from agents.simple_agent import MySimpleAgent

load_dotenv(find_dotenv())

# 创建 LLM 客户端（自动读 .env）
llm = MyLLMClient()

print("=" * 50)
print("🧪 测试1: 基础对话（无工具）")
print("=" * 50)
basic_agent = MySimpleAgent(
    name="基础助手",
    llm=llm,
    system_prompt="你是一个友好的AI助手，请用简洁明了的方式回答问题。",
    config=Config.from_env()
)

response1 = basic_agent.run("你好，请用一句话介绍你自己")
print(f"📝 回答: {response1}\n")

print("=" * 50)
print("🧪 测试2: 工具增强对话")
print("=" * 50)
tool_registry = MyToolRegistry()
calculator = CalculatorTool()
tool_registry.register_tool(calculator)

enhanced_agent = MySimpleAgent(
    name="增强助手",
    llm=llm,
    system_prompt="你是一个智能助手，可以使用计算器工具来帮助用户进行数学计算。",
    tool_registry=tool_registry,
    enable_tool_calling=True
)

response2 = enhanced_agent.run("请帮我计算 15 * 8 + 32")
print(f"📝 回答: {response2}\n")

print("=" * 50)
print("🧪 测试3: 流式响应")
print("=" * 50)
print("🌊 流式输出: ", end="")
for chunk in basic_agent.stream_run("请解释什么是人工智能"):
    pass  # 内容已在 stream_run 中实时打印
print()

print("=" * 50)
print("🧪 测试4: 动态工具管理")
print("=" * 50)
print(f"添加工具前: {basic_agent.has_tools()}")
basic_agent.add_tool(calculator)
print(f"添加工具后: {basic_agent.has_tools()}")
print(f"可用工具列表: {basic_agent.list_tools()}")

print(f"\n📜 对话历史条数: {len(basic_agent.get_history())}")