# test/10-memory-base.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.base import MemoryItem, MemoryConfig, BaseMemory
from datetime import datetime

print("=" * 50)
print("🧪 测试记忆系统地基 (base.py)")
print("=" * 50)

# 1. 测试 MemoryItem
item = MemoryItem(
    content="用户张三是一名Python开发者",
    memory_type="semantic",
    importance=0.9,
    metadata={"source": "对话", "session": "session_001"}
)
print(f"✅ 创建记忆项成功:")
print(f"   ID: {item.id}")
print(f"   内容: {item.content}")
print(f"   类型: {item.memory_type}")
print(f"   重要性: {item.importance}")
print(f"   时间: {item.timestamp}")
print(f"   摘要: {item.get_summary()}")
print(f"   字典: {item.to_dict()}\n")

# 2. 测试 MemoryConfig
config = MemoryConfig()
print(f"✅ 默认配置:")
print(f"   工作记忆容量: {config.working_memory_capacity}")
print(f"   TTL: {config.working_memory_ttl} 分钟")
print(f"   数据库路径: {config.database_path}\n")

# 3. 测试抽象基类（不能被实例化，只能被继承）
try:
    base = BaseMemory(config)
    print("❌ 错误：应该不能实例化抽象基类")
except TypeError as e:
    print(f"✅ 正确：BaseMemory 是抽象类，无法实例化")
    print(f"   错误信息: {e}\n")

print("🎉 地基验证通过！可以继续搭建 storage 和 embedding 层了。")