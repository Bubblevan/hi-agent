# -----------------------------------------------------------------------------
# 模块定位：记忆系统入口，统一导出核心数据类型
# 设计原则：所有核心类型定义在 base.py 中，__init__.py 只做 re-export，
#           避免代码重复，保证单一定源（Single Source of Truth）。
# -----------------------------------------------------------------------------

from .base import MemoryItem, MemoryConfig, BaseMemory

__all__ = [
    "MemoryItem",    # 单条记忆的数据结构
    "MemoryConfig",  # 记忆系统全局配置
    "BaseMemory",    # 所有记忆类型的抽象基类
]
