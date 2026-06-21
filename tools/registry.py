from typing import Dict, Any, Callable, Optional
from .base import MyTool

class MyToolRegistry:
    """工具注册表 - 负责注册、发现、执行工具"""

    def __init__(self):
        self._tools: Dict[str, MyTool] = {}
        self._functions: Dict[str, Dict[str, Any]] = {}  # 支持直接注册函数

    def register_tool(self, tool: MyTool):
        # 注册一个工具对象
        if tool.name in self._tools:
            print(f"警告：工具'{tool.name}'已存在将被覆盖")
        self._tools[tool.name] = tool
        print(f"工具'{tool.name}'已注册")

    