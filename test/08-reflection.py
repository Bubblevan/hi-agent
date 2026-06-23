# test_reflection_agent.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv, find_dotenv
from core.llm_client import MyLLMClient
from core.config import Config
from agents.reflection_agent import MyReflectionAgent

load_dotenv(find_dotenv())

print("=" * 60)
print("🧪 测试 Reflection Agent (生成 → 反思 → 改进)")
print("=" * 60)

# 1. 创建 LLM 客户端
llm = MyLLMClient()

# 2. 创建 Reflection Agent（使用默认提示词）
agent = MyReflectionAgent(
    name="反思助手",
    llm=llm,
    system_prompt="你是一个严谨的写作者，擅长自我审视和改进。",
    max_refinement_rounds=2,  # 最多改进两轮
    stop_if_no_improvement=True,
    config=Config.from_env()
)

# ============================================================
# 测试案例 1: 文章撰写
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 1: 撰写短文")
print("=" * 60)

task1 = "请写一段关于 '人工智能对教育的影响' 的简短观点 (100字以内)。"
print(f"任务: {task1}\n")

answer1 = agent.run(task1)
print(f"\n🎯 最终答案:\n{answer1}")

# ============================================================
# 测试案例 2: 代码生成（使用自定义提示词）
# ============================================================
print("\n" + "=" * 60)
print("📌 测试案例 2: 代码生成（自定义提示词）")
print("=" * 60)

# 创建专门用于代码生成的反思 Agent（使用自定义提示词）
code_prompts = {
    "initial": "你是一位Python专家。请编写一个Python函数来完成以下任务:\n\n任务: {task}\n\n请只输出代码，不要额外解释。",
    "reflect": "请审查以下代码，找出潜在的性能问题、bug或风格问题:\n\n# 任务: {task}\n# 代码:\n{content}\n\n请列出改进建议。如果代码已经很好，请回答 '无需改进'。",
    "refine": "请根据以下反馈改进代码:\n\n# 任务: {task}\n# 原代码:\n{last_attempt}\n# 反馈:\n{feedback}\n\n请输出改进后的完整代码。"
}

code_agent = MyReflectionAgent(
    name="代码优化助手",
    llm=llm,
    system_prompt="你是一个严谨的代码审查员，关注代码质量和性能。",
    custom_prompts=code_prompts,
    max_refinement_rounds=2,
    stop_if_no_improvement=True,
    config=Config.from_env()
)

task2 = "编写一个函数，计算一个整数列表的平均值，并返回浮点数。要求处理空列表的情况（返回0.0）。"
print(f"任务: {task2}\n")

answer2 = code_agent.run(task2)
print(f"\n🎯 最终答案:\n{answer2}")

print("\n" + "=" * 60)
print("✅ Reflection 测试全部完成！")
print("=" * 60)