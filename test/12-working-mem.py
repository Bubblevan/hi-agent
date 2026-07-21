# test/12-working-memory.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.base import MemoryConfig
from memory.manager import MemoryManager
import time

print("=" * 60)
print("🧪 测试：工作记忆 + MemoryManager")
print("=" * 60)

# 1. 初始化管理器（只启用工作记忆）
config = MemoryConfig()
manager = MemoryManager(
    config=config,
    user_id="test_user",
    enable_working=True,
    enable_episodic=False,
    enable_semantic=False
)

# 2. 添加记忆
print("\n--- 添加记忆 ---")
id1 = manager.add_memory("用户张三是一名Python开发者", memory_type="working", importance=0.9)
id2 = manager.add_memory("李四擅长前端开发", memory_type="working", importance=0.7)
id3 = manager.add_memory("王五是产品经理", memory_type="working", importance=0.6)
print(f"✅ 添加了 3 条记忆: {id1[:8]}, {id2[:8]}, {id3[:8]}")

# 3. 检索记忆
print("\n--- 检索测试 1: 'Python开发者' ---")
results = manager.retrieve_memories("Python开发者", limit=3)
for r in results:
    print(f"  {r.get_summary()}")

print("\n--- 检索测试 2: '前端' ---")
results = manager.retrieve_memories("前端", limit=3)
for r in results:
    print(f"  {r.get_summary()}")

# 4. 测试 TTL（修改配置加快过期）
print("\n--- 测试遗忘策略 (删除低重要性) ---")
deleted = manager.forget_memories(strategy="importance_based", threshold=0.8)
print(f"删除了 {deleted} 条记忆 (重要性 < 0.8)")

stats = manager.get_stats()
print(f"\n📊 当前统计: {stats}")

print("\n🎉 工作记忆测试通过！")