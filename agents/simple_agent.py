import re
from typing import Optional, Iterator, List, Dict, Any
from core.agent_base import MyAgent
from core.llm_client import MyLLMClient
from core.message import MyMessage
from core.config import Config
from tools.registry import MyToolRegistry
from tools.base import MyTool

class MySimpleAgent(MyAgent):
    """
    纯手工打造的简单对话智能体
    支持：
    1. 基础对话（无工具）
    2. 工具调用（通过 [TOOL_CALL:name:params] 格式）
    3. 流式响应
    4. 动态工具管理
    """
    def __init__(
        self,
        name: str,
        llm: MyLLMClient,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None,
        tool_registry: Optional[MyToolRegistry] = None,
        enable_tool_calling: bool = True
    ):
        
        super().__init__(name, llm, system_prompt, config)

        # 持有工具注册表实例，负责工具的查找和执行
        self.tool_registry = tool_registry
        # 工具调用开关：必须同时满足开关开启 + 注册表存在，才真正启用工具能力
        self.enable_tool_calling = enable_tool_calling and tool_registry is not None

        status = "启用" if self.enable_tool_calling else "禁用"
        print(f"{name}初始化完成，工具调用: {status}")

    def run(
        self,
        input_text: str,
        max_tool_iter: int=3,
        **kwargs
    ) -> str:
        """
        运行智能体（同步）
        """
        messages = []

        # 1. 添加增强后的系统提示词（包含工具描述）
        enhanced_system_prompt = self._get_enhanced_system_prompt()
        messages.append({"role": "system", "content": enhanced_system_prompt})

        # 2. 添加历史消息（从 MyAgent 继承的 _history）
        for msg in self._history:
            messages.append({"role": msg.role, "content": msg.content})

        # 3. 添加当前用户消息
        messages.append({"role": "user", "content": input_text})

        # 4. 如果没有启用工具调用，走简单对话逻辑
        if not self.enable_tool_calling:
            response = self.llm.invoke(messages, **kwargs)
            self.add_message(MyMessage.user(input_text))
            self.add_message(MyMessage.assistant(response))
            print(f"{self.name} 响应完成")
            return response

        # 5. 启用工具调用，走多轮迭代逻辑
        return self._run_with_tools(messages, input_text, max_tool_iter, **kwargs)
    
    def _get_enhanced_system_prompt(self) -> str:
        """构建增强的系统提示词（包含工具描述和调用格式）"""
        base_prompt = self.system_prompt or "你是一个有用的AI助手。"

        if not self.enable_tool_calling or not self.tool_registry:
            return base_prompt
        
        tools_description = self.tool_registry.get_tools_description()
        if not tools_description or tools_description == "暂无可用工具":
            return base_prompt
        
        tools_section = "\n\n## 可用工具\n"
        tools_section += "你可以使用以下工具来帮助回答问题:\n"
        tools_section += tools_description + "\n"

        tools_section += "\n## 工具调用格式\n"
        tools_section += "当需要使用工具时，请使用以下格式:\n"
        tools_section += "`[TOOL_CALL:{tool_name}:{parameters}]`\n"
        tools_section += "例如: `[TOOL_CALL:calculator:2 + 3 * 4]`\n\n"
        tools_section += "工具调用结果会自动插入到对话中，然后你可以基于结果继续回答。\n"

        return base_prompt + tools_section
    
    def _run_with_tools(
            self,
            messages: "List[Dict[str, str]]",
            input_text: str,
            max_tool_iter: int,
            **kwargs
    ) -> str:
        """支持工具调用的核心循环逻辑"""
        current_iteration = 0
        final_response = ""
        while current_iteration < max_tool_iter:
            # 调用 LLM
            response = self.llm.invoke(messages, **kwargs)

            # 检查是否有工具调用
            tool_calls = self._parse_tool_calls(response)
            if tool_calls:
                print(f"检测到 {len(tool_calls)} 个工具调用")
                tool_results = []
                clean_response = response

                for call in tool_calls:
                    result = self._execute_tool_call(call['tool_name'], call['parameters'])
                    tool_results.append(result)
                    clean_response = clean_response.replace(call['original'], "")

                # 将助手的回复（不含工具标记）加入消息
                messages.append({"role": "assistant", "content": clean_response.strip() or "正在调用工具..."})

                # 将工具执行结果加入消息
                tool_results_text = "\n\n".join(tool_results)
                messages.append({
                    "role": "user", 
                    "content": f"工具执行结果:\n{tool_results_text}\n\n请基于这些结果给出完整的回答。"
                })

                current_iteration += 1
                continue
            # 没有工具调用，这就是最终回答
            final_response = response
            break
        # 如果超过最大迭代次数还没得到最终回答，强制再调用一次
        if current_iteration >= max_tool_iter and not final_response:
            final_response = self.llm.invoke(messages, **kwargs)

        # 保存到历史记录
        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(final_response))
        print(f"{self.name} 响应完成")

        return final_response
    

    def _parse_tool_calls(self, text: str) -> List[Dict[str, str]]:
        """解析文本中的 [TOOL_CALL:name:params] 标记"""
        pattern = r'\[TOOL_CALL:([^:]+):([^\]]+)\]'
        matches = re.findall(pattern, text)

        tool_calls = []
        for tool_name, parameters in matches:
            tool_calls.append({
                'tool_name': tool_name.strip(),
                'parameters': parameters.strip(),
                'original': f'[TOOL_CALL:{tool_name}:{parameters}]'
            })

        return tool_calls
    

    def _execute_tool_call(self, tool_name: str, parameters: str) -> str:
        """执行单个工具调用"""
        if not self.tool_registry:
            return "错误: 未配置工具注册表"

        try:
            # 智能参数解析
            if tool_name == 'calculator':
                # 计算器直接传入表达式字符串
                result = self.tool_registry.execute_tool(tool_name, parameters)
            else:
                # 其他工具尝试解析为字典
                param_dict = self._parse_tool_parameters(tool_name, parameters)
                result = self.tool_registry.execute_tool(tool_name, param_dict)

            return f"工具 {tool_name} 执行结果:\n{result}"

        except Exception as e:
            return f"工具调用失败: {str(e)}"
        

    def _parse_tool_parameters(self, tool_name: str, parameters: str) -> Dict[str, Any]:
        """智能解析工具参数字符串为字典"""
        param_dict = {}

        if '=' in parameters:
            # 格式: key=value 或 action=search,query=Python
            if ',' in parameters:
                pairs = parameters.split(',')
                for pair in pairs:
                    if '=' in pair:
                        key, value = pair.split('=', 1)
                        param_dict[key.strip()] = value.strip()
            else:
                key, value = parameters.split('=', 1)
                param_dict[key.strip()] = value.strip()
        else:
            # 直接传入参数，根据工具类型智能推断
            if tool_name == 'search':
                param_dict = {'query': parameters}
            else:
                param_dict = {'input': parameters}

        return param_dict
    
    def stream_run(self, input_text: str, **kwargs) -> Iterator[str]:
        """
        流式运行方法（不支持工具调用，仅纯对话）
        """
        print(f"{self.name} 开始流式处理: {input_text}")

        messages = []

        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        for msg in self._history:
            messages.append({"role": msg.role, "content": msg.content})

        messages.append({"role": "user", "content": input_text})

        full_response = ""
        print("实时响应: ", end="")
        for chunk in self.llm.stream_invoke(messages, **kwargs):
            full_response += chunk
            print(chunk, end="", flush=True)
            yield chunk

        print()

        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(full_response))
        print(f"{self.name} 流式响应完成")


    # ---------- 便利方法 ----------
    def add_tool(self, tool: MyTool) -> None:
        """动态添加工具"""
        if not self.tool_registry:
            self.tool_registry = MyToolRegistry()
            self.enable_tool_calling = True

        self.tool_registry.register_tool(tool)
        print(f"工具 '{tool.name}' 已添加")

    def has_tools(self) -> bool:
        return self.enable_tool_calling and self.tool_registry is not None

    def remove_tool(self, tool_name: str) -> bool:
        if self.tool_registry:
            self.tool_registry.unregister(tool_name)
            return True
        return False

    def list_tools(self) -> list:
        if self.tool_registry:
            return self.tool_registry.list_tools()
        return []