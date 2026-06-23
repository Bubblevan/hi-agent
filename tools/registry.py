from typing import Dict, Any, Callable, Optional
from .base import MyTool

class MyToolRegistry:
    """工具注册表 - 负责注册、发现、执行工具"""

    def __init__(self):
        # 存储标准化 MyTool 类工具：key=工具名称，value=MyTool 实例
        self._tools: Dict[str, MyTool] = {}

        # 存储轻量函数式工具：key=工具名称，value=包含描述和函数本体的字典
        # 单独分一个字典存储，避免和类工具混合导致类型混乱
        self._functions: Dict[str, Dict[str, Any]] = {} 

    def register_tool(self, tool: MyTool):
        # 注册一个工具对象
        if tool.name in self._tools:
            print(f"警告：工具'{tool.name}'已存在将被覆盖")
        # 以工具名称为键，存入工具字典
        self._tools[tool.name] = tool
        print(f"工具'{tool.name}'已注册")

# `Callable[[str], str]` 是 Python `typing` 模块提供的 **可调用对象类型注解**
# 用来标注一个变量是「可以被执行的函数/方法」：
# - 方括号内的列表是入参类型：`[str]` 表示该函数接收 1 个字符串类型的参数
# - 最后一个值是返回值类型：结尾的 `str` 表示函数执行后返回字符串结果
# 简单来说，`Callable[[str], str]` 就代表「输入一个字符串、输出一个字符串的函数」
    def registry_function(self, name: str, description, func: Callable[[str], str]):
        """
        以轻量方式注册一个普通函数作为工具
        适合简单的单参数工具，无需定义完整的 MyTool 子类
        :param name: 工具名称（Agent 调用时使用的标识）
        :param description: 工具功能描述（会拼入提示词给 LLM 看）
        :param func: 工具对应的执行函数，入参和返回值均为字符串
        """
        if name in self._functions:
            print(f"警告：工具'{name}'已存在，将被覆盖")
        self._functions[name] = {
            "description": description,
            "func": func
        }
        print(f"函数工具‘{name}’已注册")

    def get_tools(self, name: str) -> Optional[MyTool]:
        """
        根据工具名称获取 MyTool 类工具对象
        仅返回类工具，函数工具不对外暴露原始对象
        :param name: 工具名称
        :return: 找到则返回工具实例，找不到返回 None
        """
        return self._tools.get(name)
    
    def execute_tool(self, tool_name: str, input_data: Any) -> str:
        """
        【核心方法】统一执行工具的入口
        自动识别工具类型（类工具/函数工具），做参数兼容处理后执行
        :param tool_name: 要调用的工具名称
        :param input_data: 工具入参，可能是字符串（LLM 直接输出的内容）或字典（结构化参数）
        :return: 工具执行结果字符串
        """
        # 1. 尝试查找Tool对象
        if tool_name in self._tools:
            tool = self._tools[tool_name]
            # 参数兼容逻辑：LLM 经常直接输出字符串参数，这里做自动适配
            if isinstance(input_data, str):
                # 对于计算器，直接传字符串作为参数
                if tool_name == "calculator":
                    return tool.run({"expression": input_data})
                # 对于搜索工具，使用 query 作为参数名
                if tool_name == "search":
                    return tool.run({"query": input_data})
                # 其他工具默认包装城 {'input': input_data}
                return tool.run({"input": input_data})
            else:
                # 本身就是字典格式，直接传入执行
                return tool.run(input_data)
        
        # 2. 查找轻量函数工具
        if tool_name in self._functions:
            func_info = self._functions[tool_name]
            # 直接调用函数本体传入参数
            return func_info["func"](input_data)
        
        return f"错误，未找到工具'{tool_name}'"
    
    def get_tools_description(self) -> str:
        """
        生成所有工具的格式化描述文本
        核心用途：拼接到 Agent 的系统提示词中，告诉 LLM 当前有哪些工具可用、分别是做什么的
        :return: 换行分隔的工具描述列表
        """
        descriptions = []

        # 遍历所有类工具，拼接[名称: 描述]格式
        for tool in self._tools.values():
            descriptions.append(f"- {tool.name}: {tool.description}")

        # 遍历所有函数工具，拼接同样格式的表述
        for name, info in self._functions.items():
            descriptions.append(f"- {name}: {info['description']}")

        # 合并为多行文本；没有工具时返回友好提示
        return "\n".join(descriptions) if descriptions else "暂无可用工具"

    def list_tools(self) -> list:
        """
        列出当前所有已注册的工具名称
        常用于调试、日志输出、前端展示工具列表
        :return: 工具名称组成的列表
        """
        # 合并两个字典的键，得到全量工具名称
        return list(self._tools.keys()) + list(self._functions.keys())
    
    def unregister(self, tool_name: str):
        """
        移除指定工具（支持类工具和函数工具）
        :param tool_name: 要移除的工具名称
        """
        # 先尝试从类工具中删除
        if tool_name in self._tools:
            del self._tools[tool_name]
            print(f"工具 '{tool_name}' 已移除")
        # 再尝试从函数工具中删除
        elif tool_name in self._functions:
            del self._functions[tool_name]
            print(f"函数工具 '{tool_name}' 已移除")
        else:
            print(f"工具 '{tool_name}' 不存在")

            