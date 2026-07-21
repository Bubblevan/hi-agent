# -----------------------------------------------------------------------------
# 模块定位：记忆系统统一门面（Facade）/ 中枢调度器
# 设计思想：模仿人类记忆的分层架构（工作记忆 → 情景记忆 → 语义记忆 → 感知记忆），
#           通过统一入口管理多种异构记忆存储，对外暴露一致的增删改查接口。
# 核心职责：
#   1. 统一初始化：集中配置嵌入器、记忆参数，各子记忆模块复用资源
#   2. 调度分发：将增删改查请求路由到对应类型的记忆存储实现
#   3. 结果聚合：跨多类记忆检索后统一排序、裁剪，对外输出一致结果
#   4. 生命周期管理：负责记忆遗忘、巩固、清空、统计等全生命周期操作
# 设计模式：门面模式（Facade）+ 策略模式（按 memory_type 分发到不同实现）
# -----------------------------------------------------------------------------

from typing import Optional, List, Dict, Any
from .base import MemoryItem, MemoryConfig
from .embedding import get_text_embedder

class MemoryManager:
    """
    记忆管理器（大脑中枢）
    作为整个记忆系统的对外唯一入口，协调和调度四种记忆类型：
    - working    工作记忆：短期、高频、小容量，保存最近对话上下文
    - episodic   情景记忆：长期、按事件组织，保存历史对话片段
    - semantic   语义记忆：长期、结构化知识，保存提炼后的事实与知识
    - perceptual 感知记忆：多模态感知输入，保存图像、语音等非文本信息
    """

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        user_id: str = "default_user",
        enable_working: bool = True,
        enable_episodic: bool = False,
        enable_semantic: bool = False,
        enable_perceptual: bool = False
    ):
        """
        初始化记忆管理器
        :param config: 全局记忆配置对象，统一传递给所有子记忆模块
        :param user_id: 用户唯一标识，用于多用户场景下记忆数据隔离
        :param enable_working: 是否启用工作记忆（默认开启，基础对话必需）
        :param enable_episodic: 是否启用情景记忆（长期事件记忆，按需开启）
        :param enable_semantic: 是否启用语义记忆（知识库/事实记忆，按需开启）
        :param enable_perceptual: 是否启用感知记忆（多模态记忆，按需开启）
        """

        # 配置对象：为空则使用默认配置，所有子记忆模块共享该配置
        self.config = config or MemoryConfig()
        self.user_id = user_id

        # 获取全局嵌入器单例
        # 设计考量：所有记忆类型的向量检索复用同一个嵌入器，避免重复加载模型/建立连接
        self.embedder = get_text_embedder()
        
        # 记忆类型注册表：策略模式核心，通过字符串 key 映射到具体记忆实例
        # 好处：新增记忆类型只需注册到字典，无需修改对外接口
        self.memory_types: Dict[str, Any] = {}
        
        # ---------------------------------------------------------------------
        # 延迟导入 + 按需初始化各记忆类型
        # 为什么延迟导入？
        #   各记忆类型模块（working.py 等）会继承 base 中的基类，
        #   若在文件顶部导入会形成循环依赖链，放在函数内导入可打破循环。
        # 为什么按需初始化？
        #   不是所有场景都需要全部记忆类型，按需启用可节省内存与启动时间。
        # ---------------------------------------------------------------------
        from .types.working import WorkingMemory
        from .types.episodic import EpisodicMemory
        from .types.semantic import SemanticMemory
        from .types.perceptual import PerceptualMemory

        if enable_working:
            self.memory_types['working'] = WorkingMemory(self.config, self.embedder)
            print("工作记忆 (WorkingMemory) 已启用")

        if enable_episodic:
            self.memory_types['episodic'] = EpisodicMemory(self.config, self.embedder)
            print("情景记忆 (EpisodicMemory) 已启用")

        if enable_semantic:
            self.memory_types['semantic'] = SemanticMemory(self.config, self.embedder)
            print("语义记忆 (SemanticMemory) 已启用")

        if enable_perceptual:
            self.memory_types['perceptual'] = PerceptualMemory(self.config, self.embedder)
            print("感知记忆 (PerceptualMemory) 已启用")

        print(f"MemoryManager 初始化完成，用户: {user_id}")
        print(f"   已启用的记忆类型: {list(self.memory_types.keys())}")

    # ==========================================================
    # 核心操作：添加、检索、更新、删除
    # ==========================================================
    
    def add_memory(
        self,
        content: str,
        memory_type: str = "working",
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> str:
        """
        添加一条记忆到指定类型的记忆存储中
        :param content: 记忆的文本内容
        :param memory_type: 记忆类型，可选 working/episodic/semantic/perceptual
        :param importance: 重要性评分 0.0~1.0，用于排序、遗忘和巩固判断
        :param metadata: 附加元数据字典，可存放时间戳、来源、标签等扩展信息
        :param kwargs: 透传给对应记忆类型 add 方法的额外参数
        :return: 记忆唯一 ID（memory_id），可用于后续精准更新/删除
        """
        if memory_type not in self.memory_types:
            return f"错误: 记忆类型 '{memory_type}' 未启用"
        
        # 统一构建标准记忆条目对象
        # 设计考量：所有记忆类型都使用 MemoryItem 统一数据结构，保证跨类型数据兼容
        item = MemoryItem(
            content=content,
            memory_type=memory_type,
            importance=importance,
            metadata=metadata or {}
        )

        # 分发到对应记忆类型的 add 方法执行实际存储
        memory_id = self.memory_types[memory_type].add(item, **kwargs)
        return memory_id
    
    def retrieve_memories(
        self,
        query: str,
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
        min_importance: float = 0.0,
        session_id: Optional[str] = None,
        **kwargs
    ) -> List[MemoryItem]:
        """
        跨记忆类型检索相关记忆
        执行流程：
          1. 遍历指定的所有记忆类型
          2. 各记忆类型独立执行检索（内部可能是向量检索、关键词匹配、时间排序等）
          3. 聚合所有结果后按重要性统一排序
          4. 截断到 limit 条返回

        :param query: 查询文本
        :param limit: 返回结果的最大数量
        :param memory_types: 指定检索的记忆类型列表，为 None 则检索所有已启用类型
        :param min_importance: 最低重要性阈值，过滤掉低于该值的记忆
        :param session_id: 会话ID过滤（情景记忆专用）
        :param kwargs: 透传给各记忆类型 retrieve 方法的额外参数
        :return: 按重要性降序排列的记忆条目列表
        """
        # 未指定类型则默认检索所有已启用的记忆类型
        if memory_types is None:
            memory_types = list(self.memory_types.keys())

        all_results = []
        for mem_type in memory_types:
            # 跳过未启用/不存在的类型
            if mem_type not in self.memory_types:
                continue

            # 情景记忆支持 session_id 过滤
            if mem_type == "episodic" and session_id:
                results = self.memory_types[mem_type].retrieve(
                    query=query,
                    limit=limit,
                    min_importance=min_importance,
                    session_id=session_id,
                    **kwargs
                )
            else:
                results = self.memory_types[mem_type].retrieve(
                    query=query,
                    limit=limit,
                    min_importance=min_importance,
                    **kwargs
                )
            all_results.extend(results)

        # 全局统一排序：按重要性降序，保证返回最相关/最重要的记忆
        all_results.sort(key=lambda x: x.importance, reverse=True)
        # 截断到指定数量
        return all_results[:limit]
    
    def forget_memories(
        self,
        strategy: str = "importance_based",
        threshold: float = 0.1,
        max_age_days: int = 30,
        memory_type: Optional[str] = None
    ) -> int:
        """
        执行记忆遗忘：清理过期或低价值记忆，控制内存/存储占用
        模仿人类遗忘机制：不重要的、时间久远的记忆优先被遗忘

        :param strategy: 遗忘策略
            - importance_based：基于重要性，低于阈值的遗忘
            - time_based：基于时间，超过 max_age_days 的遗忘
            - hybrid：混合策略，同时考虑重要性与时间
        :param threshold: 重要性阈值，importance_based / hybrid 策略生效
        :param max_age_days: 最大存活天数，time_based / hybrid 策略生效
        :param memory_type: 指定遗忘的记忆类型，为 None 则对所有已启用类型执行
        :return: 本次被遗忘（删除）的记忆总条数
        """
        total_deleted = 0

        # 设计考量：不同记忆类型的遗忘策略差异很大，由各自内部实现，manager 只做调度
        types_to_forget = [memory_type] if memory_type else list(self.memory_types.keys())

        for mem_type in types_to_forget:
            if mem_type not in self.memory_types:
                continue
            if hasattr(self.memory_types[mem_type], 'forget'):
                deleted = self.memory_types[mem_type].forget(
                    strategy=strategy,
                    threshold=threshold,
                    max_age_days=max_age_days
                )
                total_deleted += deleted

        return total_deleted
    
    def consolidate_memories(
        self,
        from_type: str = "working",
        to_type: str = "episodic",
        importance_threshold: float = 0.7
    ) -> int:
        """
        记忆巩固（Memory Consolidation）：将短期记忆提升为长期记忆
        对应人类记忆机制：重要的短期记忆经过加工后转化为长期记忆存储

        典型流程：从工作记忆中筛选高重要性条目，直接存入情景/语义记忆
        :param from_type: 源记忆类型（通常是短期记忆 working）
        :param to_type: 目标记忆类型（通常是长期记忆 episodic/semantic）
        :param importance_threshold: 重要性阈值，高于该值的记忆才会被巩固
        :return: 成功巩固的记忆条数
        """
        if from_type not in self.memory_types:
            print(f"源记忆类型 '{from_type}' 未启用")
            return 0
        if to_type not in self.memory_types:
            print(f"目标记忆类型 '{to_type}' 未启用")
            return 0

        # 从源记忆中检索高重要性记忆
        candidates = self.memory_types[from_type].retrieve(
            query="",
            limit=1000,
            min_importance=importance_threshold
        )

        consolidated = 0
        for item in candidates:
            # 透传到目标记忆类型
            self.memory_types[to_type].add(item)
            consolidated += 1

        print(f"已将 {consolidated} 条记忆从 {from_type} 巩固到 {to_type}")
        return consolidated

    # ==========================================================
    # 情景记忆专属便捷方法
    # ==========================================================

    def get_session_history(self, session_id: str, limit: int = 50) -> List[MemoryItem]:
        """
        获取指定会话的完整历史（仅情景记忆）
        :param session_id: 会话唯一标识
        :param limit: 返回的最大条数
        :return: 该会话的记忆条目列表
        """
        if 'episodic' not in self.memory_types:
            print("⚠️ 情景记忆未启用")
            return []
        return self.memory_types['episodic'].get_session_history(session_id, limit)

    def get_timeline(self, days: int = 30, limit: int = 50) -> List[MemoryItem]:
        """
        获取最近时间线（仅情景记忆）
        :param days: 最近多少天
        :param limit: 返回的最大条数
        :return: 时间范围内的记忆条目列表
        """
        if 'episodic' not in self.memory_types:
            print("⚠️ 情景记忆未启用")
            return []
        from datetime import datetime, timedelta
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        return self.memory_types['episodic'].get_timeline(start_time, end_time, limit)
    
    def clear_all(self, memory_type: Optional[str] = None) -> int:
        """
        清空记忆
        :param memory_type: 指定清空的记忆类型，为 None 则清空所有已启用类型
        :return: 被清空的记忆总条数
        """
        total = 0
        if memory_type:
            # 清空指定类型
            if memory_type in self.memory_types:
                total = self.memory_types[memory_type].clear()
        else:
            # 清空所有已启用类型
            for mem_type in self.memory_types.values():
                total += mem_type.clear()
        return total
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取各记忆类型的统计信息
        用于监控、调试、展示记忆容量状态
        :return: 包含各记忆类型统计数据的字典，如总条数、最早/最晚时间等
        """
        stats = {"user_id": self.user_id}
        for name, mem_type in self.memory_types.items():
            stats[name] = mem_type.get_stats()
        return stats
    