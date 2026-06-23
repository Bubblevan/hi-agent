# test_search.py
# 测试高级搜索工具，为 ReAct 做前戏
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient
from core.config import Config
from tools.registry import MyToolRegistry
from tools.builtin.search import SearchTool
from agents.simple_agent import MySimpleAgent

load_dotenv(find_dotenv())

print("=" * 60)
print("🧪 测试高级搜索工具")
print("=" * 60)

# 1. 直接测试工具
print("\n--- 1. 直接调用搜索工具 ---")
registry = MyToolRegistry()
search_tool = SearchTool()  # 自动检测可用的后端
registry.register_tool(search_tool)

query = "2024年诺贝尔物理学奖得主是谁？"
print(f"查询: {query}")
result = registry.execute_tool("search", {"query": query})
print(result)

# 2. 集成到 SimpleAgent（无工具调用） -> 但我们要启用的。
print("\n--- 2. 使用 SimpleAgent + 搜索工具 ---")
llm = MyLLMClient()

agent = MySimpleAgent(
    name="搜索助手",
    llm=llm,
    system_prompt="你是一个智能搜索助手，当用户需要最新信息时，你可以使用 search 工具来查询。",
    tool_registry=registry,
    enable_tool_calling=True,
    config=Config.from_env()
)

# 提出需要搜索的问题
question = "请帮我查找一下 Python 3.12 有哪些新特性？"
print(f"用户提问: {question}")
response = agent.run(question, max_tool_iterations=2)  # 最多两轮工具调用
print(f"\n最终回答:\n{response}")

print("\n--- 测试完成，准备进入 ReAct ---")