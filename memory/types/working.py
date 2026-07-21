# -----------------------------------------------------------------------------
# 模块定位：工作记忆（Working Memory）具体实现
# 设计对标：人类认知模型中的工作记忆系统 —— 短期、高速、容量有限、随时间快速消退
# 核心特性：
#   1. 纯内存存储：读写速度极快，无持久化开销，适合高频读写的对话上下文
#   2. 容量管控：固定最大条数，溢出时按重要性淘汰，避免内存无限增长
#   3. TTL 自动过期：记忆随时间自动失效，模拟人类短期记忆遗忘特性
#   4. 混合检索：向量语义相似度 + 关键词字面匹配 + 时间衰减加权，兼顾相关性与时效性
#   5. 优雅降级：向量嵌入失败时不中断流程，退化为纯关键词+时间排序
# -----------------------------------------------------------------------------

import math
import time
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from ..base import ForgetReport, MemoryItem, MemoryConfig, BaseMemory
from ..embedding import BaseEmbedder

class WorkingMemory(BaseMemory):
    """
    工作记忆实现类
    定位：短期高频记忆，保存最近的对话上下文、临时任务信息等
    存储介质：纯内存列表（无磁盘持久化，进程重启后丢失）
    检索方式：三重加权混合评分（向量语义 60% + 关键词匹配 30% + 时间衰减 10%）
    淘汰机制：容量满时删除重要性最低的条目；TTL 到期自动清理
    """
    def __init__(self, config: MemoryConfig, embedder: BaseEmbedder):
        """
        初始化工作记忆
        :param config: 全局记忆配置对象，从中读取工作记忆专属参数
        :param embedder: 向量嵌入器实例，用于生成记忆向量和查询向量
        """
        super().__init__(config)
        self.embedder = embedder  # 复用上层传入的嵌入器，避免重复初始化
        
        # 内存存储容器：使用列表保存所有记忆条目
        # 选择列表而非字典的原因：容量小（几十条级别），遍历排序开销可忽略，且支持顺序语义
        self._items: List[MemoryItem] = []
        
        # 容量配置：最大记忆条数，超出则触发淘汰
        self._max_capacity = config.working_memory_capacity
        # TTL 配置：记忆存活时长（分钟），超时自动过期
        self._ttl_minutes = config.working_memory_ttl
        
        print(f"工作记忆已初始化 (容量: {self._max_capacity}, TTL: {self._ttl_minutes}分钟)")
    
    # ==========================================================
    # 核心 CRUD 接口实现
    # ==========================================================
    
    def add(self, memory_item: MemoryItem) -> str:
        """
        添加一条记忆到工作记忆
        执行流程：清理过期 → 容量检查与淘汰 → 生成向量 → 写入存储
        :param memory_item: 标准记忆条目对象
        :return: 记忆条目 ID
        """
        # 1. 写入前先清理过期记忆，保证容量统计准确
        self._expire_old_memories()

        # 2. 容量管控：达到上限时淘汰重要性最低的条目
        if len(self._items) >= self._max_capacity:
            self._remove_lowest_priority()
        
        # 3. 生成文本嵌入向量，用于后续语义检索
        # 容错设计：嵌入失败不抛出异常，仅将 embedding 置为 None，退化为关键词检索
        try:
            memory_item.embedding = self.embedder.encode(memory_item.content)[0]
            if memory_item.embedding is not None and all(v == 0.0 for v in memory_item.embedding):
                memory_item.embedding = None
        except Exception:
            memory_item.embedding = None
        
        # 4. 追加到内存列表
        self._items.append(memory_item)
        return memory_item.id
    
    def retrieve(
        self,
        query: str,
        limit: int = 5,
        min_importance: float = 0.0,
        **kwargs
    ) -> List[MemoryItem]:
        """
        检索相关记忆（混合评分排序）
        评分公式：
            基础分 = 向量相似度 * 0.6 + 关键词匹配分 * 0.3 + 时间衰减分 * 0.1
            最终分 = 基础分 * (0.8 + 重要性 * 0.4)
        权重设计思路：
            - 向量语义为主（0.6）：捕捉深层语义相关性
            - 关键词为辅（0.3）：补全字面匹配，处理专有名词、精确匹配场景
            - 时间衰减（0.1）：工作记忆越新价值越高，轻微加权即可
            - 重要性加权：在 0.8~1.2 区间浮动，不主导排序，但能提升高价值记忆排名
        
        :param query: 查询文本
        :param limit: 返回结果最大数量
        :param min_importance: 最低重要性过滤阈值
        :return: 按相关性降序排列的记忆条目列表
        """
        # 检索前先清理过期记忆，避免返回已失效内容
        self._expire_old_memories()
        
        if not self._items:
            return []
        
        # 2. 计算查询向量
        # 容错：嵌入失败则退化为纯关键词+时间排序
        try:
            query_vec = self.embedder.encode(query)[0]
        except Exception:
            query_vec = None
        
        # 3. 遍历所有记忆，计算综合评分
        scored = []
        for item in self._items:
            user_id = kwargs.get("user_id")
            if user_id and item.user_id != user_id:
                continue
            # 先过滤低于重要性阈值的条目，减少后续计算
            if item.importance < min_importance:
                continue

            # 3a. 向量语义相似度（0~1）
            vector_score = 0.0
            if query_vec is not None and item.embedding is not None:
                vector_score = self._cosine_similarity(query_vec, item.embedding)
            
            # 3b. 关键词字面匹配得分（0~0.8）
            keyword_score = self._keyword_match(query, item.content)
            
            # 3c. 时间衰减得分（0.1~1.0，越新越高）
            time_decay = self._time_decay(item.timestamp)
            
            # 加权融合得到基础分
            base_score = vector_score * 0.6 + keyword_score * 0.3 + time_decay * 0.1
            # 重要性加权：将 0~1 的重要性映射到 0.8~1.2 的权重区间
            # 设计：避免重要性完全盖过相关性，仅做小幅调整
            importance_weight = 0.8 + (item.importance * 0.4)
            final_score = base_score * importance_weight
            item.metadata["relevance_score"] = final_score

            scored.append((final_score, item))

        # 按最终得分降序排序，截取前 limit 条
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]
    
    def update(self, memory_id: str, content: Optional[str] = None,
               importance: Optional[float] = None,
               user_id: Optional[str] = None, **kwargs) -> bool:
        """
        更新指定记忆的内容或重要性
        :param memory_id: 目标记忆 ID
        :param content: 新的文本内容，为 None 则不更新
        :param importance: 新的重要性值，为 None 则不更新
        :return: 是否更新成功
        """
        for item in self._items:
            if user_id and item.user_id != user_id:
                continue
            if item.id == memory_id:
                # 更新内容：同步刷新嵌入向量和时间戳
                if content is not None:
                    item.content = content
                    # 重新生成嵌入，失败则置空
                    try:
                        item.embedding = self.embedder.encode(content)[0]
                    except Exception:
                        item.embedding = None
                # 更新重要性：钳制在 0~1 区间
                if importance is not None:
                    item.importance = max(0.0, min(1.0, importance))
                if kwargs.get("metadata") is not None:
                    item.metadata = kwargs["metadata"]
                # 更新时间戳：视为"最近活跃"，重置时间衰减
                item.timestamp = datetime.now()
                return True
        return False
    
    def delete(self, memory_id: str, user_id: Optional[str] = None) -> bool:
        """
        根据 ID 删除单条记忆
        :param memory_id: 目标记忆 ID
        :return: 是否删除成功
        """
        for i, item in enumerate(self._items):
            if user_id and item.user_id != user_id:
                continue
            if item.id == memory_id:
                self._items.pop(i)
                return True
        return False
    
    def clear(self, user_id: Optional[str] = None) -> int:
        """
        清空所有工作记忆
        :return: 被清除的记忆条数
        """
        if user_id is None:
            count = len(self._items)
            self._items.clear()
            return count
        count = len([item for item in self._items if item.user_id == user_id])
        self._items = [item for item in self._items if item.user_id != user_id]
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取工作记忆统计信息
        :return: 包含类型、当前条数、容量上限、TTL 的统计字典
        """
        return {
            "type": "working",
            "count": len(self._items),
            "capacity": self._max_capacity,
            "ttl_minutes": self._ttl_minutes
        }
    
    # ==========================================================
    # 内部辅助方法
    # ==========================================================
    
    def _expire_old_memories(self):
        """
        TTL 过期清理：删除超过存活时间的记忆
        调用时机：每次 add / retrieve 操作前执行，保证数据新鲜度
        实现方式：列表推导式过滤，时间复杂度 O(n)，对小容量列表完全可接受
        """
        if not self._items:
            return
        # 计算截止时间：早于此时间的记忆全部过期
        cutoff = datetime.now() - timedelta(minutes=self._ttl_minutes)
        self._items = [item for item in self._items if item.timestamp > cutoff]
    
    def _remove_lowest_priority(self):
        """
        容量淘汰：删除重要性最低的一条记忆
        触发时机：添加新记忆且容量已满时
        淘汰策略：按重要性升序排序，移除第一条
        此处未考虑时间因素，因为工作记忆的 TTL 已单独处理过期
        """
        if not self._items:
            return
        self._items.sort(key=lambda x: x.importance)
        removed = self._items.pop(0)
        print(f"工作记忆容量已满，淘汰记忆: {removed.get_summary()}")
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        纯 Python 实现余弦相似度计算
        设计原因：不强制依赖 numpy，保持轻量；工作记忆数据量小，纯 Python 性能足够
        余弦相似度值域：[-1, 1]，值越高表示两个向量方向越接近、语义越相似
        
        :param vec1: 向量1
        :param vec2: 向量2
        :return: 余弦相似度值
        """
        if not vec1 or not vec2:
            return 0.0
        # 长度对齐：取较短长度，避免维度不一致导致报错
        min_len = min(len(vec1), len(vec2))
        vec1 = vec1[:min_len]
        vec2 = vec2[:min_len]
        
        # 点积
        dot = sum(a * b for a, b in zip(vec1, vec2))
        # 两个向量的 L2 范数
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        
        # 零向量处理：避免除零错误
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)
    
    def _keyword_match(self, query: str, content: str) -> float:
        """
        关键词字面匹配得分
        算法：基于词集的 Jaccard 近似，计算查询词在目标文本中的覆盖比例
        作用：补充向量检索的短板，处理精确关键词、专有名词、数字等场景
        上限设计：最高 0.8 分，避免关键词匹配权重超过语义匹配
        
        :param query: 查询文本
        :param content: 待匹配的记忆内容
        :return: 匹配得分（0 ~ 0.8）
        """
        if not query or not content:
            return 0.0
        # 简单按空格分词，转小写后做集合运算
        q_words = set(query.lower().split())
        c_words = set(content.lower().split())
        if not q_words:
            return 0.0
        # 计算重叠词数量占查询词总数的比例
        overlap = len(q_words & c_words)
        return overlap / len(q_words) * 0.8
    
    def _time_decay(self, timestamp: datetime) -> float:
        """
        时间衰减函数（指数衰减模型）
        设计思路：工作记忆越新价值越高，随时间呈指数级下降
        参数说明：
            - 衰减系数 0.05：约 13.86 小时衰减一半，24 小时后约为 0.3
            - 最低值 0.1：保证老旧记忆不会完全归零，仍有基础权重
            - 最高值 1.0：刚创建的记忆获得满分
        
        :param timestamp: 记忆创建/更新时间戳
        :return: 时间衰减得分（0.1 ~ 1.0）
        """

        now = datetime.now()
        # 计算记忆年龄（小时）
        age_hours = (now - timestamp).total_seconds() / 3600
        # 指数衰减公式
        decay = math.exp(-0.05 * age_hours)
        # 钳制在 [0.1, 1.0] 区间，避免衰减到 0
        return max(0.1, min(1.0, decay))
    
    def forget(self, strategy: str = "importance_based",
               threshold: float = 0.1, max_age_days: int = 30,
               user_id: Optional[str] = None) -> ForgetReport:
        """
        执行主动遗忘，支持三种策略
        :param strategy: 遗忘策略
            - importance_based：删除重要性低于阈值的记忆
            - time_based：删除超过指定天数的记忆
            - capacity_based：超出容量部分按重要性从低到高删除
        :param threshold: 重要性阈值，importance_based 策略生效
        :param max_age_days: 最大存活天数，time_based 策略生效
        :return: 本次遗忘删除的记忆条数
        """
        before = len([item for item in self._items if not user_id or item.user_id == user_id])
        
        if strategy == "importance_based":
            # 保留重要性 >= 阈值的记忆
            self._items = [
                item for item in self._items
                if (user_id and item.user_id != user_id) or item.importance >= threshold
            ]
        elif strategy == "time_based":
            # 保留 N 天以内的记忆
            cutoff = datetime.now() - timedelta(days=max_age_days)
            self._items = [
                item for item in self._items
                if (user_id and item.user_id != user_id) or item.timestamp > cutoff
            ]
        elif strategy == "capacity_based":
            # 反复移除最低重要性，直到容量符合上限
            while len([item for item in self._items if not user_id or item.user_id == user_id]) > self._max_capacity:
                self._remove_lowest_priority()
        else:
            return ForgetReport(
                memory_type="working",
                strategy=strategy,
                skipped_count=before,
                errors=[f"Unknown forget strategy: {strategy}"],
            )
        
        # 返回删除的条数
        after = len([item for item in self._items if not user_id or item.user_id == user_id])
        return ForgetReport(
            memory_type="working",
            strategy=strategy,
            deleted_count=before - after,
        )
