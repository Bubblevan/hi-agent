# agents/my_function_call_agent.py

import json
from typing import Optional, List, Dict, Any, Union
from core.agent_base import MyAgent
from core.llm_client import MyLLMClient
from core.message import MyMessage
from core.config import Config
from tools.registry import MyToolRegistry
from tools.base import MyTool

class MyFunctionCallAgent(MyAgent):
    """
    使用 OpenAI/DeepSeek 原生 tools 参数，而非文本解析
    """

    def __init__(
        self,
        name: str,
        llm: MyLLMClient,
        tool_registry: MyToolRegistry,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None,
        max_iterations: int = 5
    ):
        """
        :param name: 智能体名称
        :param llm: 我们的 LLM 客户端（必须包含 _client 属性）
        :param tool_registry: 工具注册表
        :param system_prompt: 系统提示词
        :param config: 配置对象
        :param max_iterations: 最大工具调用轮数
        """
        super().__init__(name, llm, system_prompt, config)
        self.tool_registry = tool_registry
        self.max_iterations = max_iterations
        
        # 构建 OpenAI 格式的 tool schemas
        self.tool_schemas = self._build_tool_schemas()
        
        print(f"{name} FunctionCall 模式已启动，工具数: {len(self.tool_schemas)}")

    def _build_tool_schemas(self) -> List[Dict[str, Any]]:
        """
        将我们的 MyTool 对象转换为 OpenAI function calling schema
        """
        schemas = []
        for tool_name in self.tool_registry.list_tools():
            tool = self.tool_registry.get_tools(tool_name)
            if tool is None:
                # 可能是函数工具，跳过（函数工具没有参数定义）
                continue
            
            # 获取参数定义
            params = tool.get_parameters()
            properties = {}
            required = []
            
            for p in params:
                prop = {
                    "type": p.type,
                    "description": p.description
                }
                if p.default is not None:
                    prop["description"] = f"{p.description} (默认: {p.default})"
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)
            
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            })
        
        return schemas

    def run(self, input_text: str, **kwargs) -> str:
        """
        执行 Function Calling 循环
        """
        print(f"\n{self.name} 开始处理: {input_text}")

        # 构建消息列表
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        
        # 添加历史消息
        for msg in self._history:
            messages.append({"role": msg.role, "content": msg.content})
        
        # 添加当前用户消息
        messages.append({"role": "user", "content": input_text})

        iteration = 0
        final_response = ""

        while iteration < self.max_iterations:
            iteration += 1
            print(f"\n--- 迭代 {iteration} ---")

            # 1. 调用底层 OpenAI 客户端（原生支持 tools）
            try:
                client = self.llm._client
                response = client.chat.completions.create(
                    model=self.llm.model,
                    messages=messages,
                    tools=self.tool_schemas if self.tool_schemas else None,
                    tool_choice="auto",
                    temperature=kwargs.get('temperature', 0.7),
                    max_tokens=kwargs.get('max_tokens')
                )
            except Exception as e:
                error_msg = f"LLM 调用失败: {str(e)}"
                self.add_message(MyMessage.user(input_text))
                self.add_message(MyMessage.assistant(error_msg))
                return error_msg

            # 2. 获取响应消息
            response_message = response.choices[0].message
            messages.append(response_message.model_dump())  # 保存 assistant 消息

            # 3. 检查是否有工具调用
            tool_calls = response_message.tool_calls

            if not tool_calls:
                # 没有工具调用，返回最终答案
                final_response = response_message.content or "（无内容）"
                print(f"最终回答: {final_response}")
                break

            # 4. 有工具调用，执行它们
            print(f"检测到 {len(tool_calls)} 个工具调用")
            
            for tool_call in tool_calls:
                tool_name = tool_call.function.name
                try:
                    # 解析参数（JSON 字符串 -> dict）
                    args = json.loads(tool_call.function.arguments)
                    print(f"   调用工具: {tool_name}({args})")
                    
                    # 执行工具
                    result = self.tool_registry.execute_tool(tool_name, args)
                    print(f"   执行结果: {result[:100]}...")
                    
                    # 将工具执行结果添加到消息中 (role="tool")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result
                    })
                    
                except json.JSONDecodeError as e:
                    error_content = f"工具参数解析失败: {str(e)}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": error_content
                    })
                except Exception as e:
                    error_content = f"工具执行失败: {str(e)}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": error_content
                    })

        # 如果超过最大迭代次数仍未返回，强制生成最终答案
        if not final_response:
            print("达到最大迭代次数，强制生成最终答案...")
            try:
                client = self.llm._client
                response = client.chat.completions.create(
                    model=self.llm.model,
                    messages=messages,
                    temperature=kwargs.get('temperature', 0.7)
                )
                final_response = response.choices[0].message.content or "（无法生成最终答案）"
            except Exception as e:
                final_response = f"强制生成失败: {str(e)}"

        # 保存到全局历史
        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(final_response))
        
        print(f"\n{self.name} 任务完成！")
        return final_response

    def has_tools(self) -> bool:
        return bool(self.tool_schemas)