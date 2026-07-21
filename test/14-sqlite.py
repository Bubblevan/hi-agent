import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.storage.document import SQLiteDocumentStore
from datetime import datetime, timedelta

print("=" * 60)
print("🧪 测试 SQLite 文档存储")
print("=" * 60)

# 1. 初始化
store = SQLiteDocumentStore("./test_memory.db")
print(f"✅ 存储初始化成功")

# 2. 插入测试数据
print("\n--- 插入数据 ---")
ids = []
for i, (content, mem_type, imp) in enumerate([
    ("用户张三是一名Python开发者", "episodic", 0.9),
    ("2024年6月学习了FastAPI", "episodic", 0.8),
    ("完成了第一个RAG项目", "episodic", 0.95),
    ("Python是一种解释型语言", "semantic", 0.7),
]):
    mid = f"test_{i:03d}"
    store.insert(mid, content, mem_type, importance=imp, 
                 session_id="session_001", 
                 metadata={"source": "test", "index": i})
    ids.append(mid)
    print(f"  插入: {content}")

# 3. 按ID查询
print("\n--- 按ID查询 ---")
item = store.get_by_id("test_001")
print(f"  {item}")

# 4. 条件查询
print("\n--- 条件查询 (类型=episodic, 重要性>=0.85) ---")
results = store.query(memory_type="episodic", min_importance=0.85, limit=10)
for r in results:
    print(f"  [{r['importance']}] {r['content']}")

# 5. 统计
print("\n--- 统计信息 ---")
stats = store.get_stats()
print(f"  总数: {stats['total']}")
print(f"  按类型: {stats['by_type']}")
print(f"  平均重要性: {stats['avg_importance']}")

# 6. 清理
print("\n--- 清理测试数据 ---")
deleted = store.clear()
print(f"  删除了 {deleted} 条数据")

print("\n🎉 SQLite 文档存储测试通过！")