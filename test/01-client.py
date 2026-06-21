# test_llm.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient  # 导入我们刚写的！

load_dotenv(find_dotenv())

# 1. 测试自动识别（比如你在 .env 里配置了 OPENAI_API_KEY）
llm = MyLLMClient()

# 2. 或者手动指定提供商（比如你想用 ModelScope）
# llm = MyLLMClient(provider="modelscope")

messages = [{"role": "user", "content": "你好，请用一句话介绍什么是人工智能。"}]

print("🤖 流式回答：")
for chunk in llm.stream_invoke(messages):
    print(chunk, end="", flush=True)
print("\n\n✅ 测试通过！接下来我们可以造 Message 和 Agent 基类了。")