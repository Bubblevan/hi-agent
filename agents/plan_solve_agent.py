import re
import ast
from typing import Optional, List, Dict, Any
from core.agent_base import MyAgent
from core.llm_client import MyLLMClient
from core.message import MyMessage
from core.config import Config
from tools.registry import MyToolRegistry

# ============================================================
# 1. Plan-and-Solve 提示词模板
# ============================================================
DEFAULT_PLANNER_PROMPT = """
你是一个顶级的AI规划专家。你的任务是将用户提出的复杂问题分解成一个由多个简单步骤组成的行动计划。
请确保计划中的每个步骤都是一个独立的、可执行的子任务，并且严格按照逻辑顺序排列。
你的输出必须是一个Python列表，其中每个元素都是一个描述子任务的字符串。

问题: {question}

请严格按照以下格式输出你的计划:
```python
["步骤1", "步骤2", "步骤3", ...]
```
"""

DEFAULT_EXECUTOR_PROMPT = """
你是一位顶级的AI执行专家。你的任务是严格按照给定的计划，一步步地解决问题。
你将收到原始问题、完整的计划、以及到目前为止已经完成的步骤和结果。
请你专注于解决"当前步骤"，并仅输出该步骤的最终答案，不要输出任何额外的解释或对话。

# 原始问题:
{question}

# 完整计划:
{plan}

# 历史步骤与结果:
{history}

# 当前步骤:
{current_step}

请仅输出针对"当前步骤"的回答:
"""


# ============================================================
# 2. MyPlanAndSolveAgent 类
# ============================================================
class MyPlanAndSolveAgent(MyAgent):
    """
    阶段1: Planner 分解问题
    阶段2: Executor 逐步执行（支持工具调用）
    """

    def __init__(
        self,
        name: str,
        llm: MyLLMClient,
        tool_registry: Optional[MyToolRegistry] = None,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None,
        custom_prompts: Optional[Dict[str, str]] = None,
        max_tool_iterations_per_step: int = 3
    ):
        """
        :param name: 智能体名称
        :param llm: 我们的 LLM 客户端
        :param tool_registry: 工具注册表（Executor 将使用它）
        :param system_prompt: 系统提示词
        :param config: 配置对象
        :param custom_prompts: 自定义提示词字典 {'planner': ..., 'executor': ...}
        :param max_tool_iterations_per_step: 每步执行时最大工具调用轮数
        """
        super().__init__(name, llm, system_prompt, config)
        
        self.tool_registry = tool_registry
        self.enable_tool_calling = tool_registry is not None
        
        # 使用自定义提示词或默认值
        self.planner_prompt = (custom_prompts or {}).get("planner", DEFAULT_PLANNER_PROMPT)
        self.executor_prompt = (custom_prompts or {}).get("executor", DEFAULT_EXECUTOR_PROMPT)
        self.max_tool_iterations_per_step = max_tool_iterations_per_step
        
        print(f"{name} Plan-and-Solve 模式已启动，工具调用: {'启用' if self.enable_tool_calling else '禁用'}")

    def run(self, input_text: str, **kwargs) -> str:
        """
        执行 Plan-and-Solve 流程
        """
        print(f"\n{self.name} 开始处理问题: {input_text}")

        # ----- 阶段 1: 规划 (Plan) -----
        print("\n--- 阶段 1: 规划 (Planner) ---")
        plan = self._plan(input_text, **kwargs)
        
        if not plan:
            error_msg = "规划失败，无法生成有效的步骤列表。"
            self.add_message(MyMessage.user(input_text))
            self.add_message(MyMessage.assistant(error_msg))
            return error_msg

        print(f"计划生成完成，共 {len(plan)} 步:")
        for i, step in enumerate(plan, 1):
            print(f"  步骤 {i}: {step}")

        # ----- 阶段 2: 执行 (Solve) -----
        print("\n--- 阶段 2: 执行 (Executor) ---")
        final_answer = self._execute_plan(input_text, plan, **kwargs)

        # 保存到全局历史
        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(final_answer))
        
        print(f"\n{self.name} 任务完成！")
        return final_answer

    # ==========================================================
    # 规划器 (Planner)
    # ==========================================================
    def _plan(self, question: str, **kwargs) -> List[str]:
        """
        调用 LLM 生成步骤列表
        返回: List[str] 或空列表（解析失败时）
        """
        # 构建提示词
        prompt = self.planner_prompt.format(question=question)
        messages = [{"role": "user", "content": prompt}]
        
        # 调用 LLM
        response = self.llm.invoke(messages, **kwargs)
        print(f"Planner 原始响应:\n{response}\n")

        # 解析 Python 列表
        try:
            # 尝试从响应中提取 ```python ... ``` 代码块
            code_block_match = re.search(r'```python\s*(.*?)\s*```', response, re.DOTALL)
            if code_block_match:
                list_str = code_block_match.group(1).strip()
            else:
                # 如果没有代码块，尝试直接提取 [...] 部分
                list_match = re.search(r'\[.*?\]', response, re.DOTALL)
                if list_match:
                    list_str = list_match.group(0)
                else:
                    # 回退：直接当作纯文本解析（去掉首尾空白）
                    list_str = response.strip()

            # 使用 ast.literal_eval 安全解析
            plan = ast.literal_eval(list_str)
            if isinstance(plan, list) and all(isinstance(item, str) for item in plan):
                return plan
            else:
                print(f"解析结果不是字符串列表: {plan}")
                return []
                
        except Exception as e:
            print(f"解析计划失败: {e}")
            print(f"   尝试解析的内容: {list_str}")
            return []

    # ==========================================================
    # 执行器 (Executor)
    # ==========================================================
    def _execute_plan(self, question: str, plan: List[str], **kwargs) -> str:
        """
        逐步执行计划，每一步都支持工具调用
        """
        history_parts = []  # 存储每一步的结果，用于上下文
        step_results = []   # 存储每一步的完整结果

        for idx, step in enumerate(plan, 1):
            print(f"\n--- 执行步骤 {idx}/{len(plan)}: {step} ---")

            # 构建执行器提示词
            history_str = "\n".join(history_parts)
            prompt = self.executor_prompt.format(
                question=question,
                plan="\n".join([f"{i}. {s}" for i, s in enumerate(plan, 1)]),
                history=history_str,
                current_step=step
            )

            # 如果启用了工具，使用带工具循环的执行逻辑
            if self.enable_tool_calling:
                step_result = self._execute_step_with_tools(
                    prompt, step, idx, len(plan), **kwargs
                )
            else:
                # 纯文本执行（无工具）
                messages = [{"role": "user", "content": prompt}]
                step_result = self.llm.invoke(messages, **kwargs)

            print(f"步骤 {idx} 结果:\n{step_result}\n")
            
            step_results.append(step_result)
            history_parts.append(f"步骤 {idx}: {step}\n结果: {step_result}")
            history_parts.append("---")

        # 将所有步骤结果合并为最终答案
        final_answer = self._merge_results(question, plan, step_results)
        return final_answer

    # ==========================================================
    # 带工具循环的步骤执行器（类似 SimpleAgent 的逻辑）
    # ==========================================================
    def _execute_step_with_tools(
        self, 
        prompt: str, 
        current_step: str, 
        step_idx: int, 
        total_steps: int,
        **kwargs
    ) -> str:
        """
        执行单个步骤，支持多轮工具调用
        """
        # 构建初始消息（系统提示词 + 用户提示词）
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        
        # 注入工具描述到系统提示词中（让 LLM 知道它能用工具）
        tools_desc = self.tool_registry.get_tools_description()
        if tools_desc and tools_desc != "暂无可用工具":
            tool_hint = f"\n\n## 可用工具\n{tools_desc}\n\n"
            tool_hint += "当你需要获取实时信息或进行计算时，可以使用工具。"
            tool_hint += "工具调用格式: `[TOOL_CALL:工具名:参数]`\n"
            tool_hint += "例如: `[TOOL_CALL:search:2024年诺贝尔奖]` 或 `[TOOL_CALL:calculator:15 * 8]`"
            messages[0]["content"] = (messages[0]["content"] if messages else "") + tool_hint
        
        # 添加执行器提示词
        messages.append({"role": "user", "content": prompt})

        current_iteration = 0
        final_response = ""

        while current_iteration < self.max_tool_iterations_per_step:
            # 调用 LLM
            response = self.llm.invoke(messages, **kwargs)

            # 检查是否有工具调用
            tool_calls = self._parse_tool_calls(response)

            if tool_calls:
                print(f"步骤 {step_idx} 检测到 {len(tool_calls)} 个工具调用")
                tool_results = []
                clean_response = response

                for call in tool_calls:
                    result = self._execute_tool_call(call['tool_name'], call['parameters'])
                    tool_results.append(result)
                    clean_response = clean_response.replace(call['original'], "")

                # 将助手的清理后回复加入消息
                messages.append({"role": "assistant", "content": clean_response.strip() or "正在调用工具..."})
                
                # 将工具执行结果加入消息
                tool_results_text = "\n\n".join(tool_results)
                messages.append({
                    "role": "user",
                    "content": f"工具执行结果:\n{tool_results_text}\n\n请基于这些结果继续完成当前步骤。"
                })

                current_iteration += 1
                continue

            # 没有工具调用，这是当前步骤的最终回答
            final_response = response
            break

        # 如果超过最大迭代次数还没得到最终回答，强制再调用一次
        if current_iteration >= self.max_tool_iterations_per_step and not final_response:
            final_response = self.llm.invoke(messages, **kwargs)

        return final_response

    # ==========================================================
    # 工具解析与执行（复用 SimpleAgent 的逻辑）
    # ==========================================================
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
            # 智能参数解析（兼容 SimpleAgent 的逻辑）
            if tool_name == 'calculator':
                result = self.tool_registry.execute_tool(tool_name, parameters)
            else:
                param_dict = self._parse_tool_parameters(tool_name, parameters)
                result = self.tool_registry.execute_tool(tool_name, param_dict)

            return f"工具 {tool_name} 执行结果:\n{result}"

        except Exception as e:
            return f"工具调用失败: {str(e)}"

    def _parse_tool_parameters(self, tool_name: str, parameters: str) -> Dict[str, Any]:
        """智能解析工具参数字符串为字典"""
        param_dict = {}

        if '=' in parameters:
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
            if tool_name == 'search':
                param_dict = {'query': parameters}
            else:
                param_dict = {'input': parameters}

        return param_dict

    # ==========================================================
    # 结果合并器
    # ==========================================================
    def _merge_results(self, question: str, plan: List[str], step_results: List[str]) -> str:
        """
        将所有步骤的结果合并成一个完整的最终答案
        """
        # 简单合并：如果只有一个步骤，直接返回
        if len(step_results) == 1:
            return step_results[0]

        # 多个步骤：构建一个简洁的合并摘要
        summary = f"根据以下 {len(plan)} 步分析，得出最终结论：\n\n"
        for i, (step, result) in enumerate(zip(plan, step_results), 1):
            summary += f"步骤 {i} ({step}):\n{result}\n\n"
        
        summary += f"综上所述，针对 '{question}' 的答案是：\n"
        summary += step_results[-1]  # 最后一步的结果通常包含最终答案
        
        return summary

    # ==========================================================
    # 便利方法
    # ==========================================================
    def has_tools(self) -> bool:
        return self.enable_tool_calling and self.tool_registry is not None

    def list_tools(self) -> list:
        if self.tool_registry:
            return self.tool_registry.list_tools()
        return []