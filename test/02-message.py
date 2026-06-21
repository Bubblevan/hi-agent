import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.message import MyMessage
from core.llm_client import MyLLMClient
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

# 1. 测试消息类
user_msg = MyMessage.user("你好，请介绍一下你自己")
assistant_msg = MyMessage.assistant("我是纯手工打造的智能体！")

print(user_msg)  # 输出: [user] 你好，请介绍一下你自己
print(user_msg.to_dict())  # 输出: {'role': 'user', 'content': '你好，请介绍一下你自己'}

# 2. 联动测试：把我们的消息喂给 LLM Client (这才是真正的打通！)
llm = MyLLMClient()

# 构建消息列表（用我们自己的类，转成字典）
messages = [
    MyMessage.system("你是一个严谨的AI助手").to_dict(),
    MyMessage.user("请用一句话解释什么是量子计算？").to_dict()
]

print("\n🤖 测试联动回答：")
for chunk in llm.stream_invoke(messages):
    print(chunk, end="", flush=True)
print("\n\n✅ 消息类与LLM客户端联动成功！")