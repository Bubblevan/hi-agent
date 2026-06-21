import os
from typing import Optional, Dict, Any
from pydantic import BaseModel

class Config(BaseModel):
    # LLM配置
    default_model: str = "deepseek-v4-flash"
    default_provider: str = "deepseek"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    
    # 系统配置
    debug: bool = False
    log_level: str = "INFO"
    
    # 其他配置
    max_history_length: int = 100
    
    @classmethod
    def from_env(cls) -> "Config":
        """从环境变量创建配置"""
        return cls(
            debug=os.getenv("DEBUG", "false").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            temperature=float(os.getenv("TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("MAX_TOKENS")) if os.getenv("MAX_TOKENS") else None,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()
        # 在 Pydantic V2 中，官方对所有实例方法做了统一规范：
        # 所有模型相关的方法都加上 model_ 前缀，避免和用户自定义的字段 / 方法命名冲突。
        # 旧版 V1 的 .dict()、.json() 等方法被保留但标记为废弃