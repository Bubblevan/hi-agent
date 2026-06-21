import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_client import MyLLMClient
from core.message import MyMessage
from core.config import Config
from core.agent_base import MyAgent

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())
# 我们不能直接实例化 MyAgent，因为它有抽象方法，所以我们先临时写一个子类来试
# 1. 为了测试抽象基类，我们临时实现一个最简单的子类
class TempConcreteAgent(MyAgent):
    """只是为了测试基类功能而写的临时子类"""
    def run(self, input_text: str, **kwargs) -> str:
        # 最简单的实现：直接把用户问题和历史拼接发给 LLM
        messages = self.get_history_dicts()
        messages.append(MyMessage.user(input_text).to_dict())
        
        response = self.llm.invoke(messages, **kwargs)  # 用同步方式拿结果
        
        # 存进历史
        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(response))
        
        return response

# 2. 开始测试
llm = MyLLMClient()  # 自动读取你的 .env 连 DeepSeek

# 创建一个带系统提示词的智能体
agent = TempConcreteAgent(
    name="测试小助手",
    llm=llm,
    system_prompt="你是一个喜欢用比喻来解释复杂概念的AI助手。",
    config=Config.from_env()
)

# 第一次对话
print("🧪 第一轮对话：")
response1 = agent.run("什么是大语言模型？")
print(f"回答: {response1}\n")

# 查看历史长度
print(f"📜 当前历史消息数: {len(agent.get_history())} 条")

# 第二次对话（测试历史记忆）
print("\n🧪 第二轮对话（测试上下文记忆）：")
response2 = agent.run("刚才我们聊了什么？用一句话总结。")
print(f"回答: {response2}")