from typing import Optional, Dict, Any, List
from core.agent_base import MyAgent
from core.llm_client import MyLLMClient
from core.message import MyMessage
from core.config import Config

# ============================================================
# 1. Reflection 提示词模板
# ============================================================
DEFAULT_PROMPTS = {
    "initial": """
请根据以下要求完成任务:

任务: {task}

请提供一个完整、准确的回答。
""",
    "reflect": """
请仔细审查以下回答，并找出可能的问题或改进空间:

# 原始任务:
{task}

# 当前回答:
{content}

请分析这个回答的质量，指出不足之处，并提出具体的改进建议。
如果回答已经很好，请回答"无需改进"。
""",
    "refine": """
请根据反馈意见改进你的回答:

# 原始任务:
{task}

# 上一轮回答:
{last_attempt}

# 反馈意见:
{feedback}

请提供一个改进后的回答。
"""
}


# ============================================================
# 2. MyReflectionAgent 类
# ============================================================
class MyReflectionAgent(MyAgent):
    """
    流程: 初始生成 → 反思 → 改进（可重复多轮）
    """

    def __init__(
        self,
        name: str,
        llm: MyLLMClient,
        system_prompt: Optional[str] = None,
        config: Optional[Config] = None,
        custom_prompts: Optional[Dict[str, str]] = None,
        max_refinement_rounds: int = 2,  # 最大改进轮数（不含初始生成）
        stop_if_no_improvement: bool = True  # 如果反思认为无需改进，则提前终止
    ):
        """
        :param name: 智能体名称
        :param llm: LLM 客户端
        :param system_prompt: 系统提示词
        :param config: 配置对象
        :param custom_prompts: 自定义提示词字典 
                               {'initial': ..., 'reflect': ..., 'refine': ...}
        :param max_refinement_rounds: 最大改进轮数
        :param stop_if_no_improvement: 如果反思结果为"无需改进"，是否停止
        """
        super().__init__(name, llm, system_prompt, config)
        
        # 合并默认提示词和自定义
        self.prompts = DEFAULT_PROMPTS.copy()
        if custom_prompts:
            self.prompts.update(custom_prompts)
        
        self.max_refinement_rounds = max_refinement_rounds
        self.stop_if_no_improvement = stop_if_no_improvement
        
        print(f"{name} Reflection 模式已启动，最大改进轮数: {max_refinement_rounds}")

    def run(self, input_text: str, **kwargs) -> str:
        """
        执行 Reflection 流程
        """
        print(f"\n{self.name} 开始处理任务: {input_text}")

        # ----- 阶段 1: 初始生成 -----
        print("\n--- 阶段 1: 初始生成 (Initial) ---")
        current_attempt = self._generate_initial(input_text, **kwargs)
        print(f"初始回答:\n{current_attempt}\n")

        # ----- 阶段 2: 反思与改进循环 -----
        for round_num in range(1, self.max_refinement_rounds + 1):
            print(f"\n--- 反思与改进轮次 {round_num} ---")
            
            # 2.1 反思
            feedback = self._reflect(input_text, current_attempt, **kwargs)
            print(f"反馈意见:\n{feedback}\n")
            
            # 检查是否需要改进
            if self._should_stop(feedback):
                print("认为无需改进，提前终止。")
                break
            
            # 2.2 改进
            improved = self._refine(input_text, current_attempt, feedback, **kwargs)
            print(f"改进后的回答:\n{improved}\n")
            
            current_attempt = improved

        # 保存到历史
        self.add_message(MyMessage.user(input_text))
        self.add_message(MyMessage.assistant(current_attempt))
        
        print(f"{self.name} 任务完成！")
        return current_attempt

    # ==========================================================
    # 核心子方法
    # ==========================================================

    def _generate_initial(self, task: str, **kwargs) -> str:
        """生成初始回答"""
        prompt = self.prompts["initial"].format(task=task)
        messages = self._build_messages(prompt)
        response = self.llm.invoke(messages, **kwargs)
        return response

    def _reflect(self, task: str, content: str, **kwargs) -> str:
        """反思当前回答的质量"""
        prompt = self.prompts["reflect"].format(task=task, content=content)
        messages = self._build_messages(prompt)
        response = self.llm.invoke(messages, **kwargs)
        return response

    def _refine(self, task: str, last_attempt: str, feedback: str, **kwargs) -> str:
        """根据反馈改进回答"""
        prompt = self.prompts["refine"].format(
            task=task,
            last_attempt=last_attempt,
            feedback=feedback
        )
        messages = self._build_messages(prompt)
        response = self.llm.invoke(messages, **kwargs)
        return response

    def _should_stop(self, feedback: str) -> bool:
        """
        判断是否应该停止（基于反馈内容）
        如果反馈包含"无需改进"等关键词，且配置了停止标志，则返回 True
        """
        if not self.stop_if_no_improvement:
            return False
        
        # 简单的关键词检测（可以更复杂）
        stop_indicators = ["无需改进", "已经很好", "不需要改进", "可以了", "完美"]
        for indicator in stop_indicators:
            if indicator in feedback:
                return True
        return False

    def _build_messages(self, user_content: str) -> List[Dict[str, str]]:
        """构建消息列表（系统提示词 + 用户消息）"""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": user_content})
        return messages

    # ==========================================================
    # 流式支持（可选）
    # ==========================================================
    def stream_run(self, input_text: str, **kwargs):
        """
        流式执行（简化版：只流式输出初始生成，然后逐轮输出）
        实际可考虑流式输出每个阶段的结果
        """
        # 这里仅演示如何扩展，简单返回生成器
        from typing import Iterator
        
        print(f"\n🌊 {self.name} 流式处理任务: {input_text}")
        
        # 初始生成流式输出
        prompt = self.prompts["initial"].format(task=input_text)
        messages = self._build_messages(prompt)
        
        full_response = ""
        print("初始生成: ", end="")
        for chunk in self.llm.stream_invoke(messages, **kwargs):
            full_response += chunk
            print(chunk, end="", flush=True)
            yield chunk
        print()
        
        # 执行反思和改进（这里简化，省略流式输出细节）
        # 实际上你可以递归地流式输出后续阶段，但为了简洁，我们直接调用同步方法
        # 并一次性返回最终结果。
        # 这里我们不重复实现，直接调用 run 并输出最终结果
        final = self.run(input_text, **kwargs)
        yield final