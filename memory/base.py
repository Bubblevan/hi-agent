import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

# ============================================================
# 1. 记忆项 (MemoryItem) - 每一条记忆的标准化格式
# ============================================================
class MemoryItem(BaseModel):
    """单条记忆的数据结构"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default_user"
    content: str                      # 记忆内容
    memory_type: str                  # working / episodic / semantic / perceptual
    timestamp: datetime = Field(default_factory=datetime.now)
    importance: float = 0.5           # 重要性 0.0 ~ 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 扩展元数据
    
    # 向量嵌入（预留，后续由 embedding 服务填充）
    embedding: Optional[List[float]] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于存储到数据库）"""
        return self.model_dump()

    def get_summary(self) -> str:
        """获取简短摘要"""
        preview = self.content[:50] + "..." if len(self.content) > 50 else self.content
        return f"[{self.memory_type}] {preview} (重要性: {self.importance:.2f})"


class MemorySearchResult(BaseModel):
    """Unified scored retrieval result used when merging memory sources."""

    item: MemoryItem
    score: float = 0.0
    rank: int = 0
    source: str = ""

    @property
    def id(self) -> str:
        return self.item.id


class ForgetReport(BaseModel):
    """Structured report returned by every memory forget implementation."""

    memory_type: str
    strategy: str
    deleted_count: int = 0
    skipped_count: int = 0
    errors: List[str] = Field(default_factory=list)
    
# ============================================================
# 2. 记忆配置 (MemoryConfig) - 系统参数
# ============================================================
class MemoryConfig(BaseModel):
    """记忆系统全局配置"""

    # 工作记忆配置
    working_memory_capacity: int = 50       # 最大容量
    working_memory_ttl: int = 60            # 生存时间（分钟）
    
    # 存储路径配置
    database_path: str = "./memory_data/memory.db"

    # Qdrant 向量数据库配置
    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "hello_agents_vectors"

    # Neo4j 图数据库配置
    neo4j_uri: Optional[str] = None
    neo4j_user: Optional[str] = None
    neo4j_password: Optional[str] = None
    
    # 嵌入服务配置
    embedding_model: str = "qwen3.7-text-embedding"  # 或 sentence-transformers/all-MiniLM-L6-v2
    embedding_provider: str = "dashscope"       # dashscope / local / tfidf
   
    # 通用
    default_importance: float = 0.5
    
    @classmethod
    def from_env(cls) -> "MemoryConfig":
        """从环境变量加载配置（预留，后续扩展）"""
        import os
        return cls(
            qdrant_url=os.getenv("QDRANT_URL"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY"),
            neo4j_uri=os.getenv("NEO4J_URI"),
            neo4j_user=os.getenv("NEO4J_USERNAME"),
            neo4j_password=os.getenv("NEO4J_PASSWORD"),
        )
    
# ============================================================
# 3. 记忆基类 (BaseMemory) - 所有记忆类型的抽象接口
# ============================================================
from abc import ABC, abstractmethod
class BaseMemory(ABC):
    """
    所有具体记忆（WorkingMemory, EpisodicMemory 等）必须继承此类。
    """
    def __init__(self, config: MemoryConfig):
        self.config = config
        self._name = self.__class__.__name__
    
    @abstractmethod
    def add(self, memory_item: MemoryItem) -> str:
        """
        添加一条记忆
        Returns: memory_id
        """
        pass

    @abstractmethod
    def retrieve(self, query: str, limit: int = 5, **kwargs) -> List[MemoryItem]:
        """
        检索记忆
        Returns: 匹配的记忆列表
        """
        pass

    @abstractmethod
    def update(self, memory_id: str, content: Optional[str] = None,
               importance: Optional[float] = None,
               user_id: Optional[str] = None, **kwargs) -> bool:
        """更新记忆，返回是否成功"""
        pass

    @abstractmethod
    def delete(self, memory_id: str, user_id: Optional[str] = None) -> bool:
        """删除记忆，返回是否成功"""
        pass

    @abstractmethod
    def clear(self, user_id: Optional[str] = None) -> int:
        """清空所有记忆，返回删除数量"""
        pass

    @abstractmethod
    def forget(
        self,
        strategy: str = "importance_based",
        threshold: float = 0.1,
        max_age_days: int = 30,
        user_id: Optional[str] = None
    ) -> ForgetReport:
        """执行遗忘并返回结构化报告"""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息（条数、类型分布等）"""
        pass

    def __str__(self) -> str:
        return f"{self._name}(config={self.config})"
    
    
