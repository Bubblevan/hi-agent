from typing import Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel  # 只依赖 Pydantic 做数据校验，轻量且可靠

# 限制消息角色，只允许这四种（兼容 OpenAI 标准）
MessageRole = Literal["user", "assistant", "system", "tool"]

class MyMessage(BaseModel):
    content: str
    role: MessageRole
    timestamp: datetime = None
    metadata: Optional[Dict[str, Any]] = None

    def __init__(self, content: str, role: MessageRole, **kwargs):
        # 重写 __init__ 只是为了自动填充当前时间，方便日常使用
        super().__init__(
            content=content,
            role=role,
            timestamp=kwargs.get('timestamp', datetime.now()),
            metadata=kwargs.get('metadata', {})
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        核心转换方法：将内部消息对象 → OpenAI API 可接收的标准字典
        为什么不直接用字典？
        - 做一层格式隔离：内部可以随意加字段（timestamp、metadata），对外输出始终保持API要求的结构
        - 后续如果切换其他大模型厂商，只需修改这个方法，上层业务代码无需改动
        """
        return {
            "role": self.role,
            "content": self.content
        }
    
    def __str__(self) -> str:
        """
        自定义对象的字符串表示
        直接 print(消息对象) 时，会输出易读的 [角色] 内容 格式，方便调试和日志打印
        """
        return f"[{self.role}] {self.content}"
    
    # ------------------------------
    # 快捷构造类方法（工厂模式）
    # 避免每次手动传 role 参数，减少手写字符串出错的概率
    # MyMessage.user("你好") 比 MyMessage(content="你好", role="user") 更短更直观
    # ------------------------------
    @classmethod
    def user(cls, content: str) -> "MyMessage":
        """快速创建一条用户消息"""
        return cls(content=content, role="user")

    @classmethod
    def assistant(cls, content: str) -> "MyMessage":
        """快速创建一条助手消息"""
        return cls(content=content, role="assistant")

    @classmethod
    def system(cls, content: str) -> "MyMessage":
        """快速创建一条系统提示词消息"""
        return cls(content=content, role="system")