# test/14-episodic-memory.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.base import MemoryConfig, MemoryItem
from memory.embedding import get_text_embedder
from memory.types.episodic import EpisodicMemory
from datetime import datetime, timedelta

print("=" * 60)
print("🧪 测试情景记忆 (EpisodicMemory)")
print("=" * 60)

# 初始化
config = MemoryConfig(database_path="./test_episodic.db")
embedder = get_text_embedder()
memory = EpisodicMemory(config, embedder)

# 1. 添加一些事件
print("\n--- 添加事件 ---")
events = [
    ("2024年6月1日，开始学习Python基础", 0.7, {"session_id": "session_001"}),
    ("2024年6月15日，完成第一个Python项目", 0.9, {"session_id": "session_001"}),
    ("2024年7月1日，学习了FastAPI框架", 0.8, {"session_id": "session_001"}),
    ("2024年7月20日，部署了第一个Web应用", 0.85, {"session_id": "session_001"}),
    ("2024年8月5日，开始学习机器学习", 0.75, {"session_id": "session_002"}),
]

for content, importance, metadata in events:
    item = MemoryItem(content=content, memory_type="episodic", 
                      importance=importance, metadata=metadata)
    memory.add(item)
    print(f"  ✅ {content}")

# 2. 检索测试
print("\n--- 检索: 'Python 项目' ---")
results = memory.retrieve("Python 项目", limit=3)
for r in results:
    print(f"  {r.get_summary()}")

print("\n--- 检索: '部署 Web' ---")
results = memory.retrieve("部署 Web", limit=3)
for r in results:
    print(f"  {r.get_summary()}")

# 3. 按会话检索
print("\n--- 会话 session_001 的历史 ---")
history = memory.get_session_history("session_001", limit=10)
for i, r in enumerate(history, 1):
    print(f"  {i}. {r.content} ({r.timestamp.strftime('%Y-%m-%d')})")

# 4. 统计
print("\n--- 统计信息 ---")
stats = memory.get_stats()
print(f"  情景记忆条数: {stats['count']}")
print(f"  平均重要性: {stats['avg_importance']}")

# 5. 清理
print("\n--- 清理测试数据 ---")
deleted = memory.clear()
print(f"  删除了 {deleted} 条数据")

print("\n🎉 情景记忆测试通过！")