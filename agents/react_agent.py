import re
from typing import Optional, Iterator, List, Dict, Any, Tuple
from core.agent_base import MyAgent
from core.llm_client import MyLLMClient
from core.message import MyMessage
from core.config import Config
from tools.registry import MyToolRegistry
from tools.base import MyTool

# 默认 ReAct 提示词模板
MY_REACT_PROMPT = """你是一个具备推理和行动能力的AI助手。你可以通过思考分析问题，然后调用合适的工具来获取信息，最终给出准确的答案。

## 可用工具
{tools}

## 工作流程
请严格按照以下格式进行回应，每次只能执行一个步骤:

Thought: 分析当前问题，思考需要什么信息或采取什么行动。
Action: 选择一个行动，格式必须是以下之一:
- `{{tool_name}}[{{tool_input}}]` - 调用指定工具
- `Finish[最终答案]` - 当你有足够信息给出最终答案时

## 重要提醒
1. 每次回应必须包含 Thought 和 Action 两部分
2. 工具调用的格式必须严格遵循: 工具名[参数]
3. 只有当你确信有足够信息回答问题时，才使用 Finish
4. 如果工具返回的信息不够，继续使用其他工具或相同工具的不同参数

## 当前任务
**Question:** {question}

## 执行历史
{history}

现在开始你的推理和行动:
"""

class MyReActAgent(MyAgent):
    """
    遵循 Thought -> Action -> Observation 循环
    """
    def __init__(
        self,
        name: str,
        llm: MyLLMClient,
        tool_registry: MyToolRegistry,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None,
        max_steps: int = 5,
        custom_prompt: Optional[str] = None
    ):
        # 调用父类初始化（MyAgent）
        super().__init__(name, llm, system_prompt, config)
        
        self.tool_registry = tool_registry
        self.max_steps = max_steps
        self.prompt_template = custom_prompt if custom_prompt else MY_REACT_PROMPT
        
        # 用于存储当前任务的执行历史（Thought/Action/Observation 字符串列表）
        self.react_history: List[str] = []
        print(f"{name} ReActAgent 初始化完成，最大步数: {max_steps}")

    def run(self, input_text: str, **kwargs) -> str:
        # 重置当前执行历史
        self.react_history = []
        current_step = 0

        while current_step < self.max_steps:
            current_step += 1
            print(f"\n--- ReAct 第 {current_step} 步 ---")

            # 1. 获取工具描述
            tools_desc = self.tool_registry.get_tools_description()
            if not tools_desc or tools_desc == "暂无可用工具":
                tools_desc = "（注意：当前没有可用工具，你只能依靠自身知识回答）"

            # 2. 格式化提示词
            history_str = "\n".join(self.react_history)
            prompt = self.prompt_template.format(
                tools=tools_desc,
                question=input_text,
                history=history_str
            )

            # 3. 调用 LLM（只传用户消息，因为提示词已经包含了所有上下文）
            messages = [{"role": "user", "content": prompt}]
            response_text = self.llm.invoke(messages, **kwargs)
            
            print(f"LLM 响应:\n{response_text}\n")

            # 4. 解析 Thought 和 Action
            thought, action = self._parse_output(response_text)

            # 如果解析失败（没有 Action），强行结束
            if not action:
                print("未解析到 Action，终止循环")
                final_answer = "抱歉，我无法按照 ReAct 格式处理这个问题。"
                self._save_to_history(input_text, final_answer)
                return final_answer

            # 5. 检查是否完成
            if action.startswith("Finish"):
                final_answer = self._parse_finish(action)
                print(f"任务完成！最终答案: {final_answer}")
                self._save_to_history(input_text, final_answer)
                return final_answer
            
            # 6. 执行工具调用
            tool_name, tool_input = self._parse_action(action)
            if not tool_name:
                # 如果工具名解析失败，记录错误并继续
                observation = f"解析 Action 失败: {action}"
                print(observation)
                self.react_history.append(f"Thought: {thought}")
                self.react_history.append(f"Action: {action}")
                self.react_history.append(f"Observation: {observation}")
                continue

            # 执行工具
            try:
                observation = self.tool_registry.execute_tool(tool_name, tool_input)
                print(f"执行工具 '{tool_name}'，输入: '{tool_input}'")
                print(f"观察结果: {observation[:100]}...")
            except Exception as e:
                observation = f"工具执行异常: {str(e)}"
                print(observation)

            # 7. 将这一步加入历史记录
            self.react_history.append(f"Thought: {thought}")
            self.react_history.append(f"Action: {action}")
            self.react_history.append(f"Observation: {observation}")

        # 如果超过最大步数，强制结束
        final_answer = "抱歉，我无法在限定步数内完成这个任务。"
        print(f"达到最大步数 {self.max_steps}，强制结束")
        self._save_to_history(input_text, final_answer)
        return final_answer
    
    def _parse_output(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        从 LLM 响应中解析出 Thought 和 Action
        返回: (thought, action)
        """
        thought = None
        action = None

        # 尝试用正则提取 Thought 和 Action
        # 匹配 "Thought: ..." 直到 "Action:" 之前
        thought_match = re.search(r"Thought:\s*(.*?)\s*Action:", text, re.DOTALL | re.IGNORECASE)
        if thought_match:
            thought = thought_match.group(1).strip()
        else:
            # 如果没找到 Action，可能是只有 Thought
            # 尝试直接找 Action
            pass

        # 提取 Action
        action_match = re.search(r"Action:\s*(.*)", text, re.DOTALL | re.IGNORECASE)
        if action_match:
            action = action_match.group(1).strip()
        else:
            # 尝试从文本末尾直接提取 Finish 或工具调用
            # 有些模型可能不写 "Action:" 前缀，直接写 "Finish[...]" 或 "Calculator[...]"
            finish_match = re.search(r"Finish\s*\[(.*?)\]", text, re.DOTALL | re.IGNORECASE)
            if finish_match:
                action = f"Finish[{finish_match.group(1)}]"
            else:
                tool_match = re.search(r"(\w+)\s*\[(.*?)\]", text, re.DOTALL | re.IGNORECASE)
                if tool_match:
                    action = f"{tool_match.group(1)}[{tool_match.group(2)}]"

        if not thought:
            thought = "(未明确输出思考过程)"

        return thought, action
    

    def _parse_action(self, action: str) -> Tuple[Optional[str], Optional[str]]:
        """
        解析 Action 字符串，返回 (tool_name, tool_input)
        例如 "Calculator[2+3]" -> ("Calculator", "2+3")
        """
        pattern = r"^(\w+)\s*\[(.*?)\]$"
        match = re.match(pattern, action)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return None, None
    
    def _parse_finish(self, action: str) -> str:
        """解析 Finish[最终答案]"""
        pattern = r"Finish\s*\[(.*?)\]$"
        match = re.match(pattern, action, re.DOTALL)
        if match:
            return match.group(1).strip()
        # 如果格式不标准，尝试直接去掉 "Finish" 前缀
        return action.replace("Finish", "").strip("[] ")

    def _save_to_history(self, user_input: str, final_answer: str):
        """将最终对话保存到 MyAgent 的历史记录中（继承自基类的 _history）"""
        self.add_message(MyMessage.user(user_input))
        self.add_message(MyMessage.assistant(final_answer))