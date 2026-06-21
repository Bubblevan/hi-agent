from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class ToolParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None

class MyTool(ABC):
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def run(self, parameters: Dict[str, Any]) -> str:
        """执行工具，接收参数字典，返回字符串结果"""
        pass

    @abstractmethod
    def get_parameters(self) -> List[ToolParameter]:
        """返回工具的参数定义列表"""
        pass

    def to_dict(self) -> Dict[str, Any]:
        """返回工具的基本信息（用于注册表描述）"""
        return {
            "name": self.name,
            "description": self.description,
        }
    
    