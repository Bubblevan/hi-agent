# -----------------------------------------------------------------------------
# 模块定位：情景记忆（Episodic Memory）具体实现
# 设计对标：人类认知模型中的情景记忆 —— 按时间序列存储"经历过的事件"，持久化保存
# 与工作记忆的区别：
#   - 工作记忆：纯内存、短期、小容量、高速读写，存当前对话上下文
#   - 情景记忆：SQLite持久化、长期、大容量、按事件/会话组织，存历史对话记录
# 核心特性：
#   1. 持久化存储：基于 SQLite 落盘，进程重启不丢失
#   2. 事件时序性：天然按时间组织，支持会话回溯、时间范围查询
#   3. 两阶段检索：先数据库条件粗筛候选，再本地精细评分排序，兼顾性能与精度
#   4. 接口统一：继承 BaseMemory，可被 MemoryManager 无缝调度
# -----------------------------------------------------------------------------

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import math

from ..base import MemoryItem, MemoryConfig, BaseMemory
from ..embedding import BaseEmbedder
from ..storage.document import SQLiteDocumentStore

class EpisodicMemory(BaseMemory):
    """
    情景记忆实现类
    定位：长期事件型记忆，保存完整的对话历史、事件片段，按时间/会话组织
    存储介质：SQLite 关系型数据库（持久化落盘）
    检索方式：关键词匹配 + 时间衰减 + 重要性 三重加权混合评分
    业务场景：回溯历史对话、按会话查记录、时间线浏览、长期记忆巩固目标
    """
    
    def __init__(self, config: MemoryConfig, embedder: BaseEmbedder):
        """
        初始化情景记忆
        :param config: 全局记忆配置对象，读取数据库路径等参数
        :param embedder: 向量嵌入器实例（预留后续升级向量检索）
        """
        super().__init__(config)
        self.embedder = embedder  # 预留：后续升级向量检索时使用
        
        # 初始化 SQLite 持久化存储层
        # 设计：数据持久化能力委托给 SQLiteDocumentStore，本层专注业务逻辑
        self.store = SQLiteDocumentStore(config.database_path)
        
        print(f"情景记忆已初始化 (数据库: {config.database_path})")

    # ==========================================================
    # 核心 CRUD 接口实现（符合 BaseMemory 统一接口）
    # ==========================================================
    
    def add(self, memory_item: MemoryItem) -> str:
        """
        添加一条情景记忆（持久化到 SQLite）
        :param memory_item: 标准记忆条目对象
        :return: 记忆 ID
        """
        # 从元数据中提取会话ID，没有则用 default 兜底
        session_id = memory_item.metadata.get("session_id", "default")
        
        # 调用存储层执行插入，将内存对象转为数据库字段
        success = self.store.insert(
            memory_id=memory_item.id,
            content=memory_item.content,
            memory_type="episodic",
            timestamp=memory_item.timestamp,
            importance=memory_item.importance,
            metadata=memory_item.metadata,
            session_id=session_id,
            user_id=memory_item.user_id
        )

        if not success:
            raise RuntimeError(f"情景记忆存储失败: {memory_item.id}")
        
        return memory_item.id
    
    def retrieve(
        self,
        query: str,
        limit: int = 5,
        min_importance: float = 0.0,
        session_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        **kwargs
    ) -> List[MemoryItem]:
        """
        检索情景记忆（两阶段混合检索）
        执行流程：
          1. 粗筛：利用 SQLite 索引按条件过滤，取出候选集（limit*3 条）
          2. 精排：对候选集计算综合相关性得分，按得分排序
          3. 转换：将数据库字典转为标准 MemoryItem 对象返回
        设计原因：全量数据精细评分性能差，先靠数据库索引缩小范围，再做复杂计算
        
        :param query: 查询文本
        :param limit: 返回结果最大条数
        :param min_importance: 最低重要性阈值
        :param session_id: 按会话过滤
        :param start_time: 起始时间
        :param end_time: 结束时间
        :return: 按相关性降序排列的记忆条目列表
        """

        # 第一阶段：数据库粗筛，多取 3 倍候选，保证后续排序后结果质量
        candidates = self.store.query(
            memory_type="episodic",
            user_id=kwargs.get("user_id"),
            session_id=session_id,
            min_importance=min_importance,
            start_time=start_time,
            end_time=end_time,
            limit=limit * 3,
            order_by="timestamp DESC"
        )
        
        if not candidates:
            return []
        
        # 第二阶段：对每条候选计算相关性得分
        scored = []
        for cand in candidates:
            score = self._calculate_relevance(query, cand)
            scored.append((score, cand))
        
        # =====================================================================
        # 【语法详解：lambda 匿名函数 + sorted 排序】
        # =====================================================================
        # 1. 场景：对 (分数, 候选数据) 的元组列表，按分数进行降序排序
        # 2. key=lambda x: x[0] 表示：取列表每个元素的第 0 位（即分数）作为排序依据
        # 3. reverse=True 表示降序，分数高的排在前面
        # 4. 等价完整写法：
        #    def get_score(item):
        #        return item[0]
        #    scored.sort(key=get_score, reverse=True)
        # 5. 为什么用 lambda：排序规则极其简单，单独定义函数冗余，一行表达式足够清晰
        # =====================================================================
        scored.sort(key=lambda x: x[0], reverse=True)

        # 第三阶段：截取前 limit 条，转为标准 MemoryItem 对象
        results = []
        for _, cand in scored[:limit]:
            item = MemoryItem(
                id=cand["id"],
                user_id=cand.get("user_id", "default_user"),
                content=cand["content"],
                memory_type="episodic",
                timestamp=datetime.fromisoformat(cand["timestamp"]),
                importance=cand["importance"],
                metadata=cand.get("metadata", {})
            )
            results.append(item)
        
        return results
    
    def update(self, memory_id: str, content: Optional[str] = None,
               importance: Optional[float] = None,
               user_id: Optional[str] = None, **kwargs) -> bool:
        """
        更新情景记忆（直接委托存储层执行）
        :param memory_id: 目标记忆 ID
        :param content: 新内容
        :param importance: 新重要性
        :return: 是否更新成功
        """
        return self.store.update(
            memory_id=memory_id,
            content=content,
            importance=importance,
            metadata=kwargs.get("metadata"),
            user_id=user_id
        )
    
    def delete(self, memory_id: str, user_id: Optional[str] = None) -> bool:
        """
        删除单条情景记忆
        :param memory_id: 目标记忆 ID
        :return: 是否删除成功
        """
        return self.store.delete(memory_id, user_id=user_id)
    
    def clear(self, user_id: Optional[str] = None) -> int:
        """
        清空所有情景记忆
        :return: 被清空的记录条数
        """
        return self.store.clear(memory_type="episodic", user_id=user_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取情景记忆统计信息
        :return: 统计字典
        """
        stats = self.store.get_stats()
        return {
            "type": "episodic",
            "count": stats["by_type"].get("episodic", 0),
            "total": stats["total"],
            "avg_importance": stats["avg_importance"],
            "db_path": stats["db_path"]
        }
    
    # ==========================================================
    # 情景记忆特有业务方法
    # ==========================================================
    
    def get_session_history(
        self,
        session_id: str,
        limit: int = 50,
        user_id: Optional[str] = None
    ) -> List[MemoryItem]:
        """
        获取单个会话的完整历史记录（按时间正序）
        业务场景：回溯整段对话、会话复盘
        :param session_id: 会话 ID
        :param limit: 最大返回条数
        :return: 按时间升序排列的记忆列表
        """
        results = self.store.query(
            memory_type="episodic",
            user_id=user_id,
            session_id=session_id,
            limit=limit,
            order_by="timestamp ASC"
        )

        # =====================================================================
        # 【语法详解：列表推导式（List Comprehension）】
        # =====================================================================
        # 1. 作用：一行代码从可迭代对象生成新列表，替代 for 循环 + append 的样板代码
        # 2. 格式：[表达式 for 元素 in 可迭代对象]
        # 3. 本例等价于：
        #    items = []
        #    for r in results:
        #        item = MemoryItem(...)
        #        items.append(item)
        # 4. 优势：代码更紧凑、执行效率略高于普通循环，Python 中非常常用
        # 5. 扩展：还可以加条件过滤，如 [x for x in lst if x > 0]
        # =====================================================================
        return [
            MemoryItem(
                id=r["id"],
                user_id=r.get("user_id", "default_user"),
                content=r["content"],
                memory_type="episodic",
                timestamp=datetime.fromisoformat(r["timestamp"]),
                importance=r["importance"],
                metadata=r.get("metadata", {})
            )
            for r in results
        ]
    
    def get_timeline(self, start_time: Optional[datetime] = None,
                     end_time: Optional[datetime] = None,
                     limit: int = 50,
                     user_id: Optional[str] = None) -> List[MemoryItem]:
        """
        按时间线获取事件（默认最近 30 天，倒序排列）
        业务场景：浏览历史记忆时间线、查看近期记录
        :param start_time: 起始时间，默认 30 天前
        :param end_time: 结束时间，默认当前时间
        :param limit: 最大返回条数
        :return: 按时间降序排列的记忆列表
        """
        # 默认时间范围：最近 30 天
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(days=30)
        
        results = self.store.query(
            memory_type="episodic",
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            order_by="timestamp DESC"
        )
        
        # 同样使用列表推导式批量转换对象
        return [
            MemoryItem(
                id=r["id"],
                user_id=r.get("user_id", "default_user"),
                content=r["content"],
                memory_type="episodic",
                timestamp=datetime.fromisoformat(r["timestamp"]),
                importance=r["importance"],
                metadata=r.get("metadata", {})
            )
            for r in results
        ]
    
    # ==========================================================
    # 内部辅助方法
    # ==========================================================
    
    def _calculate_relevance(self, query: str, doc: Dict[str, Any]) -> float:
        """
        计算查询与文档的综合相关性评分
        评分公式：基础分 = 关键词匹配*0.5 + 时间衰减*0.2 + 重要性*0.3
        权重设计思路：
          - 关键词匹配（0.5）：相关性核心依据，占比最高
          - 重要性（0.3）：情景记忆长期保存，重要性权重比工作记忆更高
          - 时间衰减（0.2）：长期记忆时间敏感度低于短期工作记忆，占比降低
        
        :param query: 查询文本
        :param doc: 单条记忆文档字典
        :return: 相关性分数
        """
        # 1. 关键词字面匹配得分
        keyword_score = self._keyword_match(query, doc["content"])
        
        # 2. 时间近因性得分（越近越高）
        timestamp = datetime.fromisoformat(doc["timestamp"])
        time_score = self._time_decay(timestamp)
        
        # 3. 记忆重要性本身
        importance = doc["importance"]
        
        # 加权融合
        base_score = keyword_score * 0.5 + time_score * 0.2 + importance * 0.3
        
        return base_score
    
    def _keyword_match(self, query: str, content: str) -> float:
        """
        关键词匹配得分（基于正则分词的词集重叠率）
        相比工作记忆的空格分词更鲁棒：支持中英文混合、自动过滤标点
        :param query: 查询文本
        :param content: 待匹配内容
        :return: 匹配得分 0~1
        """
        if not query or not content:
            return 0.0
        
        # =====================================================================
        # 【语法详解：正则表达式 re.findall + Unicode 中文区间】
        # =====================================================================
        # 1. re.findall(pattern, string)：返回所有匹配的子串列表
        # 2. 正则 [\w\u4e00-\u9fa5]+ 含义：
        #    - \w：匹配字母、数字、下划线
        #    - \u4e00-\u9fa5：匹配所有常见中文字符的 Unicode 区间
        #    - +：匹配前面的规则一次或多次（即连续的字符作为一个词）
        # 3. 作用：把文本拆分为"单词/中文连续字"的列表，自动过滤标点、空格
        # 4. 比单纯 split() 更通用：中文不需要空格分隔，也能正确切分
        # =====================================================================
        import re
        q_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', query.lower()))
        c_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', content.lower()))
        
        if not q_words:
            return 0.0
        
        # 计算查询词在目标文本中的重叠比例
        overlap = len(q_words & c_words)
        return min(1.0, overlap / len(q_words))
    
    def _time_decay(self, timestamp: datetime) -> float:
        """
        两段式时间衰减函数
        设计贴合人类记忆规律：
          - 24小时内：记忆清晰，分数在 0.8~1.0 之间缓慢下降
          - 超过24小时：缓慢衰减，最低保留 0.2 基础分，不会完全遗忘
        :param timestamp: 记忆时间戳
        :return: 时间衰减得分 0.2~1.0
        """
        now = datetime.now()
        # 计算记忆年龄（小时）
        age_hours = (now - timestamp).total_seconds() / 3600
        
        # 第一段：24小时内，从 1.0 线性降到 0.8
        if age_hours <= 24:
            return 0.8 + 0.2 * (1 - age_hours / 24)
        # 第二段：超过24小时，缓慢线性衰减，最低 0.2
        else:
            decay = max(0.2, 1.0 - 0.02 * (age_hours - 24))
            return decay
    
    def __str__(self) -> str:
        """
        【魔法方法】自定义对象字符串表示
        打印对象时自动调用，直观展示当前记忆条数
        """
        return f"EpisodicMemory(count={self.store.count('episodic')})"
