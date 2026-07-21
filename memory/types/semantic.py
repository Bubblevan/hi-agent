# -----------------------------------------------------------------------------
# 模块定位：语义记忆（Semantic Memory）具体实现
# 设计对标：人类认知模型中的语义记忆 —— 存储抽象知识、概念、事实，而非具体事件
# 与其他记忆的区别：
#   - 工作记忆：短期、纯内存、存对话上下文
#   - 情景记忆：长期、按事件/时间组织、存对话历史记录
#   - 语义记忆：长期、按知识语义组织、存提炼后的事实与知识，主打语义检索
# 核心架构：双存储分层设计
#   - SQLite：权威数据源，存储文本内容与元数据，保证数据持久化与一致性
#   - Qdrant：向量索引，负责语义相似度检索，加速召回
# 降级策略：Qdrant 不可用时，自动降级为 SQLite + 关键词匹配检索，功能可用仅效果下降
# -----------------------------------------------------------------------------
from typing import List, Dict, Any, Optional
from datetime import datetime
import math

from ..base import MemoryItem, MemoryConfig, BaseMemory
from ..embedding import BaseEmbedder
from ..storage.document import SQLiteDocumentStore
from ..storage.qdrant import QdrantVectorStore

class SemanticMemory(BaseMemory):
    """
    语义记忆实现类
    定位：长期知识型记忆，保存提炼后的结构化知识、事实、概念，主打语义相似度检索
    存储介质：SQLite（元数据持久化） + Qdrant（向量语义检索）
    检索方式：优先向量语义检索，不可用时自动降级为关键词匹配检索
    业务场景：知识库问答、事实回忆、知识沉淀、长期经验复用
    """
    def __init__(self, config: MemoryConfig, embedder: BaseEmbedder):
        """
        初始化语义记忆
        :param config: 全局记忆配置对象，读取数据库、向量库参数
        :param embedder: 向量嵌入器实例，用于生成文本向量
        """
        super().__init__(config)
        self.embedder = embedder
        
        # 第一层：SQLite 文档存储，作为权威数据源，保证数据持久化
        self.store = SQLiteDocumentStore(config.database_path)
        
        # 第二层：Qdrant 向量存储，作为语义检索索引，加速相似度查询
        self.vector_store = QdrantVectorStore(
            collection_name=config.qdrant_collection or "semantic_vectors",
            vector_size=embedder.dimension,
            url=config.qdrant_url,
            api_key=config.qdrant_api_key
        )
        
        # 向量检索可用标记：决定后续检索走向量路线还是关键词降级路线
        self._use_vector = self.vector_store.is_available()
        mode = "向量检索 (Qdrant)" if self._use_vector else "关键词检索 (SQLite 降级)"
        print(f"语义记忆已初始化 (模式: {mode})")

    # ==========================================================
    # 核心 CRUD 接口实现
    # ==========================================================
    
    def add(self, memory_item: MemoryItem) -> str:
        """
        添加一条语义记忆
        执行流程：
          1. 生成文本向量（失败则为 None，不阻断主流程）
          2. 写入 SQLite（权威存储，必须成功，失败则抛出异常）
          3. 向量可用时同步写入 Qdrant（失败仅打印警告，不影响主数据）
        设计原则：SQLite 是事实基准，向量库是加速索引，索引失败不能影响数据写入
        
        :param memory_item: 标准记忆条目对象
        :return: 记忆 ID
        """
        # 1. 生成向量嵌入
        try:
            vector = self.embedder.encode(memory_item.content)[0]
        except Exception as e:
            print(f"嵌入生成失败: {e}")
            vector = None
        
        # 2. 写入 SQLite 持久化存储（必须成功）
        session_id = memory_item.metadata.get("session_id", "default")
        success = self.store.insert(
            memory_id=memory_item.id,
            content=memory_item.content,
            memory_type="semantic",
            timestamp=memory_item.timestamp,
            importance=memory_item.importance,
            metadata=memory_item.metadata,
            session_id=session_id,
            user_id=memory_item.user_id
        )
        
        if not success:
            raise RuntimeError(f"语义记忆存储失败: {memory_item.id}")
        
        # 3. 同步写入向量库（仅当向量生成成功且向量库可用时）
        if vector and self._use_vector:
            self.vector_store.add_vector(
                vector=vector,
                memory_id=memory_item.id,
                metadata={
                    "memory_type": "semantic",
                    "user_id": memory_item.user_id,
                    "importance": memory_item.importance,
                    "session_id": session_id
                }
            )
        
        return memory_item.id
    
    def retrieve(
        self,
        query: str,
        limit: int = 5,
        min_importance: float = 0.0,
        session_id: Optional[str] = None,
        **kwargs
    ) -> List[MemoryItem]:
        """
        检索语义记忆（双方案自动降级）
        方案 A（优先）：Qdrant 向量语义检索 + SQLite 补全元数据
        方案 B（降级）：SQLite 粗筛 + 本地关键词评分排序
        
        :param query: 查询文本
        :param limit: 返回结果最大条数
        :param min_importance: 最低重要性阈值
        :param session_id: 按会话过滤
        :return: 按相关性降序排列的记忆条目列表
        """
        # ----- 方案 A：向量语义检索（优先） -----
        if self._use_vector:
            try:
                # 生成查询向量
                query_vector = self.embedder.encode(query)[0]
                
                # 构造过滤条件：固定 memory_type，可选 session_id
                filter_payload = {"memory_type": "semantic"}
                if kwargs.get("user_id"):
                    filter_payload["user_id"] = kwargs["user_id"]
                if session_id:
                    filter_payload["session_id"] = session_id
                
                # 向量召回：多取 2 倍结果，便于后续二次过滤排序
                results = self.vector_store.search_vectors(
                    query_vector=query_vector,
                    limit=limit * 2,
                    score_threshold=0.3,  # 相似度阈值，过滤过低的结果
                    filter_payload=filter_payload
                )
                if results:
                    # 回查 SQLite 获取完整的记忆数据（向量库只存 ID 和分数）
                    memory_items = []
                    for r in results:
                        mem_id = r["memory_id"]
                        doc = self.store.get_by_id(mem_id)
                        # 二次校验重要性阈值
                        if (
                            doc
                            and doc["importance"] >= min_importance
                            and (
                                not kwargs.get("user_id")
                                or doc.get("user_id") == kwargs["user_id"]
                            )
                        ):
                            item = MemoryItem(
                                id=doc["id"],
                                user_id=doc.get("user_id", "default_user"),
                                content=doc["content"],
                                memory_type="semantic",
                                timestamp=datetime.fromisoformat(doc["timestamp"]),
                                importance=doc["importance"],
                                metadata=doc.get("metadata", {})
                            )
                            # 把向量相似度分数存入元数据，便于调试和二次排序
                            item.metadata["vector_score"] = r["score"]
                            item.metadata["relevance_score"] = r["score"]
                            memory_items.append(item)
                    # =====================================================================
                    # 【语法详解：lambda 匿名函数 + 列表排序】
                    # =====================================================================
                    # 1. 作用：按记忆的 importance 属性进行降序排序
                    # 2. key=lambda x: x.importance 表示：取列表每个元素的 importance 属性作为排序依据
                    # 3. reverse=True 表示降序，重要性高的排在前面
                    # 4. 设计说明：此处用重要性做二次排序，也可改为按 vector_score 排序，
                    #    当前设计兼顾语义相似度与知识重要性，避免低重要性的高相似度结果排在前面
                    # =====================================================================
                    memory_items.sort(
                        key=lambda x: x.metadata.get("relevance_score", 0.0),
                        reverse=True,
                    )
                    return memory_items[:limit]
                
            except Exception as e:
                # 向量检索异常：打印警告，自动降级到关键词方案
                print(f"向量检索失败，降级到关键词: {e}")
                # 不 return，继续执行下方的降级方案

        # ----- 方案 B：关键词检索（兜底降级） -----
        # 第一步：从 SQLite 按条件粗筛候选集
        candidates = self.store.query(
            memory_type="semantic",
            user_id=kwargs.get("user_id"),
            session_id=session_id,
            min_importance=min_importance,
            limit=limit * 3,
            order_by="importance DESC"
        )
        if not candidates:
            return []
        
        # 第二步：本地计算关键词匹配分，综合重要性加权排序
        scored = []
        for cand in candidates:
            score = self._keyword_match(query, cand["content"])
            # 综合评分：关键词匹配 60% + 重要性 40%
            final_score = score * 0.6 + cand["importance"] * 0.4
            scored.append((final_score, cand))

        # 按综合得分降序排序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 第三步：转为标准 MemoryItem 对象返回
        results = []
        for _, cand in scored[:limit]:
            item = MemoryItem(
                id=cand["id"],
                user_id=cand.get("user_id", "default_user"),
                content=cand["content"],
                memory_type="semantic",
                timestamp=datetime.fromisoformat(cand["timestamp"]),
                importance=cand["importance"],
                metadata=cand.get("metadata", {})
            )
            item.metadata["relevance_score"] = self._keyword_match(query, cand["content"])
            results.append(item)
        
        return results
    
    def update(self, memory_id: str, content: Optional[str] = None,
               importance: Optional[float] = None,
               user_id: Optional[str] = None, **kwargs) -> bool:
        """
        更新语义记忆
        注意：更新内容时需要同步更新向量库，先删旧向量再添加新向量，保证数据一致性
        :param memory_id: 目标记忆 ID
        :param content: 新内容，None 则不更新
        :param importance: 新重要性，None 则不更新
        :return: 是否更新成功
        """
        # 第一步：更新 SQLite 主数据
        success = self.store.update(
            memory_id=memory_id,
            content=content,
            importance=importance,
            metadata=kwargs.get("metadata"),
            user_id=user_id
        )
        # 第二步：如果更新了内容且向量库可用，同步更新向量
        if success and content and self._use_vector:
            try:
                # 先删除旧向量
                self.vector_store.delete_by_memory_id(memory_id, user_id=user_id)
                # 生成新向量并写入
                vector = self.embedder.encode(content)[0]
                doc = self.store.get_by_id(memory_id)
                if doc:
                    self.vector_store.add_vector(
                        vector=vector,
                        memory_id=memory_id,
                        metadata={
                            "memory_type": "semantic",
                            "importance": doc["importance"],
                            "session_id": doc.get("session_id", "default")
                        }
                    )
            except Exception as e:
                # 向量更新失败不影响主数据，仅打印警告
                print(f"更新向量失败: {e}")

        return success
    
    def delete(self, memory_id: str, user_id: Optional[str] = None) -> bool:
        """
        删除单条语义记忆（双存储同步删除）
        :param memory_id: 目标记忆 ID
        :return: 是否删除成功
        """
        success = self.store.delete(memory_id, user_id=user_id)
        # SQLite 删除成功且向量库可用时，同步删除向量
        if success and self._use_vector:
            self.vector_store.delete_by_memory_id(memory_id, user_id=user_id)
        return success
    
    def clear(self, user_id: Optional[str] = None) -> int:
        """
        清空所有语义记忆（双存储同步清空）
        :return: 被清空的记录条数
        """
        count = self.store.clear(memory_type="semantic", user_id=user_id)
        if self._use_vector:
            filter_payload = {"memory_type": "semantic"}
            if user_id:
                filter_payload["user_id"] = user_id
            self.vector_store.clear(filter_payload=filter_payload)
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取语义记忆统计信息
        :return: 统计字典，包含条数、向量模式、数据库路径等
        """
        stats = self.store.get_stats()
        return {
            "type": "semantic",
            "count": stats["by_type"].get("semantic", 0),
            "total": stats["total"],
            "avg_importance": stats["avg_importance"],
            "vector_mode": "Qdrant" if self._use_vector else "SQLite (降级)",
            "db_path": stats["db_path"]
        }
    
    # ==========================================================
    # 内部辅助方法
    # ==========================================================
    
    def _keyword_match(self, query: str, content: str) -> float:
        """
        关键词匹配得分（正则分词 + 词集重叠率）
        降级检索时使用，算法与情景记忆保持一致，保证跨模块行为统一
        :param query: 查询文本
        :param content: 待匹配内容
        :return: 匹配得分 0~1
        """
        if not query or not content:
            return 0.0
        
        # =====================================================================
        # 【语法详解：正则分词 + 中文 Unicode 区间】
        # =====================================================================
        # re.findall(r'[\w\u4e00-\u9fa5]+', text)
        # - \w：匹配字母、数字、下划线
        # - \u4e00-\u9fa5：匹配所有常用中文字符
        # - +：匹配连续字符作为一个词
        # 作用：自动过滤标点、空格，中英文混合场景都能正确切分出词语
        # =====================================================================
        import re
        q_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', query.lower()))
        c_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', content.lower()))
        
        if not q_words:
            return 0.0
        
        overlap = len(q_words & c_words)
        return min(1.0, overlap / len(q_words))
    
    def __str__(self) -> str:
        """
        【魔法方法】自定义对象字符串表示
        直观展示记忆条数和向量检索开关状态
        """
        return f"SemanticMemory(count={self.store.count('semantic')}, vector={'ON' if self._use_vector else 'OFF'})"
    
