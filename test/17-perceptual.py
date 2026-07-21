import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.base import MemoryConfig, MemoryItem
from memory.embedding import get_text_embedder
from memory.types.perceptual import PerceptualMemory
from datetime import datetime

print("=" * 60)
print("🧪 测试感知记忆 (PerceptualMemory)")
print("=" * 60)

# 初始化
config = MemoryConfig(database_path="./test_perceptual.db")
embedder = get_text_embedder()
memory = PerceptualMemory(config, embedder)

# 1. 添加文本记忆（用文本模态）
print("\n--- 添加文本记忆 ---")
item1 = MemoryItem(
    content="一张展示Python代码的截图，包含函数定义和调用",
    memory_type="perceptual",
    importance=0.8,
    metadata={"modality": "text"}
)
memory.add(item1)
print("  ✅ 文本记忆已添加")

# 2. 模拟图像记忆（无实际文件，仅描述）
print("\n--- 添加模拟图像记忆 ---")
item2 = MemoryItem(
    content="用户上传的机器学习模型架构图",
    memory_type="perceptual",
    importance=0.9,
    metadata={"modality": "image", "file_path": "mock_image.png"}
)
memory.add(item2, file_path="mock_image.png", modality="image")
print("  ✅ 图像记忆已添加")

# 3. 添加音频记忆（模拟）
print("\n--- 添加模拟音频记忆 ---")
item3 = MemoryItem(
    content="用户语音提问：'如何优化Python代码性能？'",
    memory_type="perceptual",
    importance=0.7,
    metadata={"modality": "audio", "file_path": "mock_audio.wav"}
)
memory.add(item3, file_path="mock_audio.wav", modality="audio")
print("  ✅ 音频记忆已添加")

# 4. 检索测试
print("\n--- 检索: 'Python 代码 截图' ---")
results = memory.retrieve("Python 代码 截图", limit=5)
for r in results:
    mod = r.metadata.get("modality", "unknown")
    print(f"  [{mod}] {r.get_summary()}")

print("\n--- 仅检索图像 ---")
results = memory.retrieve("机器学习", limit=3, modality="image")
for r in results:
    print(f"  {r.get_summary()}")

# 5. 统计
print("\n--- 统计信息 ---")
stats = memory.get_stats()
print(f"  总数: {stats['count']}")
print(f"  向量模式: {stats['vector_mode']}")

print("\n🎉 感知记忆测试通过！")