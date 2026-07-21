# test/15-manager-full.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.base import MemoryConfig
from memory.manager import MemoryManager

print("=" * 60)
print("🧪 测试完整记忆系统 (Working + Episodic + Semantic)")
print("=" * 60)

# 1. 初始化管理器（启用三种记忆）
config = MemoryConfig(database_path="./test_full_memory.db")
manager = MemoryManager(
    config=config,
    user_id="test_user",
    enable_working=True,
    enable_episodic=True,
    enable_semantic=True
)

print("\n--- 添加记忆 ---")

# 工作记忆（临时）
manager.add_memory("当前用户正在询问 Python 性能优化", memory_type="working", importance=0.7)

# 情景记忆（具体事件）
manager.add_memory(
    "2024年6月25日，完成了记忆系统第一版开发", 
    memory_type="episodic", 
    importance=0.9,
    metadata={"session_id": "dev_session", "event_type": "milestone"}
)

# 语义记忆（抽象知识）
manager.add_memory(
    "Python 是一种解释型、面向对象的高级编程语言。它的设计哲学强调代码可读性和简洁的语法。",
    memory_type="semantic",
    importance=0.85,
    metadata={"category": "programming", "language": "python"}
)
manager.add_memory(
    "机器学习是人工智能的一个子领域，通过算法让计算机从数据中学习模式。主要包括监督学习、无监督学习和强化学习。",
    memory_type="semantic",
    importance=0.8,
    metadata={"category": "ai", "subfield": "ml"}
)

print("✅ 添加了 4 条记忆（覆盖 3 种类型）")

# 2. 检索测试
print("\n--- 全局检索: 'Python' ---")
results = manager.retrieve_memories("Python", limit=5)
for r in results:
    print(f"  [{r.memory_type}] {r.get_summary()}")

print("\n--- 仅语义记忆: '机器学习' ---")
results = manager.retrieve_memories("机器学习", limit=3, memory_types=["semantic"])
for r in results:
    print(f"  {r.get_summary()}")

print("\n--- 情景会话历史 (session: dev_session) ---")
history = manager.get_session_history("dev_session", limit=10)
for r in history:
    print(f"  {r.content} ({r.timestamp.strftime('%Y-%m-%d %H:%M')})")

# 3. 统计
print("\n--- 统计信息 ---")
stats = manager.get_stats()
print(f"  用户: {stats['user_id']}")
for mem_type, stat in stats.items():
    if mem_type == "user_id":
        continue
    print(f"  {mem_type}: {stat.get('count', 0)} 条")

print("\n🎉 完整记忆系统测试通过！")