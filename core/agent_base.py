from abc import ABC, abstractmethod
from typing import Optional, List
from .message import MyMessage
from .llm_client import MyLLMClient
from .config import Config

class MyAgent(ABC):
    def __init__(
        self,
        name: str,
        llm: MyLLMClient,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None
    ):
        """
        智能体通用初始化逻辑（所有子类共享，无需重复实现）
        :param name: 智能体名称，用于标识和日志输出
        :param llm: 大模型客户端实例（所有 Agent 的核心"计算发动机"）
        :param system_prompt: 系统提示词，用于定义 Agent 人设、能力边界、输出规则
        :param config: 全局配置实例，不传则自动从环境变量加载默认配置
        """
        self.name = name
        self.llm = llm
        self.system_prompt = system_prompt
        self.config = config or Config.from_env()  # 自动从 .env 读取配置

        # 初始化对话历史列表，用来存放 MyMessage 对象
        # 单下划线开头是 Python 约定的「受保护属性」
        # 设计意图：不希望外部代码直接修改这个列表，必须通过 add_message / clear_history 操作
        self._history: List[MyMessage] = []

        # 如果系统提示词存在，自动把它加入到历史中（作为第一条系统消息）
        if self.system_prompt:
            self.add_message(MyMessage.system(self.system_prompt))

        print(f"智能体 '{self.name}' 初始化完成 (模型: {self.llm.model})")

    @abstractmethod
    def run(self, input_text: str, **kwargs) -> str:
        """
        【抽象方法，必须由子类实现】
        智能体的核心运行入口，所有子类都必须实现该方法
        :param input_text: 用户输入的文本内容
        :param kwargs: 扩展参数，不同 Agent 可自定义（如工具列表、流式开关等）
        :return: 智能体最终输出的回复文本
        设计意义：
        - 强制所有 Agent 对外提供一致的调用入口
        - 具体逻辑由子类自由实现（简单直接调用LLM / ReAct思考循环 / 工具调用等）
        """
        pass

    def add_message(self, message: MyMessage):
        """
        向对话历史中追加一条消息（唯一的历史写入入口）
        内置长度截断逻辑：超过配置上限时自动删除最早的消息
        :param message: 要添加的消息对象（必须是 MyMessage 类型）
        """
        self._history.append(message)

        # 历史长度超限处理：超过配置的最大长度时，弹出最老的一条消息
        # 实现滑动窗口效果，避免历史无限增长导致 token 溢出
        if len(self._history) > self.config.max_history_length:
            self._history.pop(0)

    def clear_history(self):
        """
        清空对话历史（但保留系统提示词）
        典型场景：用户开启新对话时调用，重置上下文但保留 Agent 人设
        """
        # 先清空整个历史列表
        self._history.clear()
        # 如果有系统提示词，重新添加回去，保证人设设定不丢失
        if self.system_prompt:
            self.add_message(MyMessage.system(self.system_prompt))

    def get_history(self) -> List[MyMessage]:
        """
        获取当前对话历史的副本
        为什么返回副本而不是原列表？
        - 遵循封装原则：禁止外部代码直接修改内部历史状态
        - 外部拿到副本后随意修改，不会影响 Agent 内部的真实历史数据
        :return: 历史消息列表的浅拷贝
        """
        return self._history.copy()
    
    def get_history_dicts(self) -> List[dict]:
        """
        便捷工具方法：将历史消息批量转为字典格式
        核心用途：直接喂给 LLM 客户端的聊天接口（大模型接口只认字典格式的消息）
        避免每次调用 LLM 都要手动写列表推导式做格式转换
        :return: 符合 OpenAI 标准格式的字典列表
        """
        return [msg.to_dict() for msg in self._history]
    
    def __str__(self) -> str:
        """
        自定义对象的字符串表示
        直接打印 Agent 对象时输出友好信息，方便调试和日志排查
        """
        return f"MyAgent(name={self.name}, model={self.llm.model})"