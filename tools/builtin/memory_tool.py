# -----------------------------------------------------------------------------
# 模块定位：Agent 工具层 - 记忆能力封装
# 架构位置：处于 Agent 工具系统与记忆子系统之间，将底层记忆能力包装为标准工具接口
# 核心职责：
#   1. 遵循 MyTool 工具规范，对外提供统一的 execute 调用入口
#   2. 将 Agent 的指令（action + 参数）转发给 MemoryManager 执行
#   3. 自动注入会话ID、用户ID等元数据，实现记忆的会话隔离与用户隔离
#   4. 将底层返回结果格式化为自然可读文本，便于大模型理解并生成回复
# 设计模式：命令模式（Command Pattern）- 通过 action 字符串路由到具体处理函数
# -----------------------------------------------------------------------------

from typing import Optional, Dict, Any, List
from datetime import datetime

from tools.base import MyTool, ToolParameter
from memory.manager import MemoryManager
from memory.base import MemoryConfig


class MemoryTool(MyTool):
    """
    记忆工具类 - 为 Agent 提供标准化的记忆读写能力
    作为 Agent 可调用的标准工具之一，封装了记忆系统的全量操作。
    大模型可通过指定 action + 参数的方式调用，完成记忆的增删改查、遗忘、整合等操作。
    """

    def __init__(
        self,
        user_id: str = "default_user",
        memory_config: Optional[MemoryConfig] = None,
        enable_working: bool = True,
        enable_episodic: bool = False,
        enable_semantic: bool = False,
        enable_perceptual: bool = False
    ):
        """
        初始化记忆工具
        :param user_id: 用户唯一标识，用于多用户场景下记忆数据隔离
        :param memory_config: 记忆配置对象，不传则使用默认配置
        :param enable_*: 是否启用对应类型的记忆
        """
        super().__init__(
            name="memory",
            description="记忆工具 - 可以存储和检索对话历史、知识和经验"
        )
        self.user_id = user_id
        self.config = memory_config or MemoryConfig()

        # 初始化记忆管理器（中枢调度器），所有实际记忆操作都委托给它执行
        self.manager = MemoryManager(
            config=self.config,
            user_id=user_id,
            enable_working=enable_working,
            enable_episodic=enable_episodic,
            enable_semantic=enable_semantic,
            enable_perceptual=enable_perceptual
        )
        # 当前会话ID：第一次执行操作时自动生成
        self.current_session_id: Optional[str] = None

        print(f"MemoryTool 初始化完成，用户: {user_id}")

    def run(self, parameters: Dict[str, Any]) -> str:
        """
        标准工具执行入口，将参数字典转发给 execute
        :param parameters: 必须包含 'action' 键，其余键作为操作参数
        :return: 操作结果字符串
        """
        action = parameters.get("action", "search")
        kwargs = {k: v for k, v in parameters.items() if k != "action"}
        return self.execute(action, **kwargs)

    def get_parameters(self) -> List[ToolParameter]:
        """
        返回记忆工具的参数定义
        """
        return [
            # ---------- 必选参数 ----------
            ToolParameter(
                name="action",
                type="string",
                description="操作类型: add/search/summary/stats/update/remove/forget/consolidate/clear_all/timeline/session",
                required=True
            ),
            # ---------- 通用参数 ----------
            ToolParameter(
                name="content",
                type="string",
                description="记忆内容（add/update 时使用）",
                required=False
            ),
            ToolParameter(
                name="query",
                type="string",
                description="搜索查询（search 时使用）",
                required=False
            ),
            ToolParameter(
                name="memory_type",
                type="string",
                description="记忆类型: working/episodic/semantic/perceptual",
                required=False,
                default="working"
            ),
            ToolParameter(
                name="memory_types",
                type="string",
                description="搜索时指定多个记忆类型，逗号分隔，如 'working,episodic'",
                required=False
            ),
            ToolParameter(
                name="limit",
                type="integer",
                description="返回结果数量限制（search/summary/timeline 时使用）",
                required=False,
                default=5
            ),
            ToolParameter(
                name="importance",
                type="number",
                description="重要性 0~1（add 时使用）",
                required=False,
                default=0.5
            ),
            ToolParameter(
                name="min_importance",
                type="number",
                description="最低重要性阈值（search 时过滤低价值记忆）",
                required=False,
                default=0.0
            ),
            ToolParameter(
                name="memory_id",
                type="string",
                description="记忆ID（update/remove 时使用）",
                required=False
            ),
            ToolParameter(
                name="session_id",
                type="string",
                description="会话ID（按会话检索情景记忆时使用）",
                required=False
            ),
            # ---------- 遗忘操作参数 ----------
            ToolParameter(
                name="strategy",
                type="string",
                description="遗忘策略: importance_based/time_based/hybrid（forget 时使用）",
                required=False,
                default="importance_based"
            ),
            ToolParameter(
                name="threshold",
                type="number",
                description="重要性阈值（importance_based/hybrid 策略时，低于此值的被遗忘）",
                required=False,
                default=0.1
            ),
            ToolParameter(
                name="max_age_days",
                type="integer",
                description="最大存活天数（time_based/hybrid 策略时，超过此天数的被遗忘）",
                required=False,
                default=30
            ),
            # ---------- 巩固操作参数 ----------
            ToolParameter(
                name="from_type",
                type="string",
                description="源记忆类型（consolidate 时使用，通常是 working）",
                required=False,
                default="working"
            ),
            ToolParameter(
                name="to_type",
                type="string",
                description="目标记忆类型（consolidate 时使用，通常是 episodic/semantic）",
                required=False,
                default="episodic"
            ),
            ToolParameter(
                name="importance_threshold",
                type="number",
                description="重要性阈值（consolidate 时，高于此值的才会被巩固）",
                required=False,
                default=0.7
            ),
            # ---------- 感知记忆参数 ----------
            ToolParameter(
                name="modality",
                type="string",
                description="模态类型: image/audio/video/text（perceptual 专用）",
                required=False
            ),
            ToolParameter(
                name="days",
                type="integer",
                description="时间线查询天数（timeline 时使用）",
                required=False,
                default=30
            ),
        ]

    def execute(self, action: str, **kwargs) -> str:
        """
        【统一入口】工具执行方法，所有记忆操作都通过此方法调用
        符合 Agent 工具的调用约定：接收动作名 + 关键字参数，返回字符串结果

        :param action: 操作类型，支持 add/search/summary/stats/update/remove/forget/consolidate/clear_all/timeline/session
        :param kwargs: 对应操作的参数，透传给具体处理函数
        :return: 格式化后的文本结果，供大模型读取
        """
        # 首次调用自动生成会话ID，格式：session_年月日_时分秒
        if self.current_session_id is None:
            self.current_session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 自动将会话ID注入元数据
        if "metadata" not in kwargs:
            kwargs["metadata"] = {}
        kwargs["metadata"]["session_id"] = self.current_session_id

        # ---------- 命令分发：根据 action 路由到对应私有方法 ----------
        if action == "add":
            return self._add_memory(**kwargs)
        elif action == "search":
            return self._search_memory(**kwargs)
        elif action == "summary":
            return self._get_summary(**kwargs)
        elif action == "stats":
            return self._get_stats(**kwargs)
        elif action == "update":
            return self._update_memory(**kwargs)
        elif action == "remove":
            return self._remove_memory(**kwargs)
        elif action == "forget":
            return self._forget_memories(**kwargs)
        elif action == "consolidate":
            return self._consolidate_memories(**kwargs)
        elif action == "clear_all":
            return self._clear_all(**kwargs)
        elif action == "timeline":
            return self._get_timeline(**kwargs)
        elif action == "session":
            return self._get_session(**kwargs)
        else:
            return f"错误: 不支持的操作 '{action}'。支持: add, search, summary, stats, update, remove, forget, consolidate, clear_all, timeline, session"

    # ==========================================================
    # 具体操作实现（私有方法，仅内部调用）
    # ==========================================================

    def _add_memory(
        self,
        content: str = "",
        memory_type: str = "working",
        importance: float = 0.5,
        **kwargs
    ) -> str:
        """
        添加记忆
        """
        if not content:
            return "错误: 记忆内容不能为空"
        try:
            importance = max(0.0, min(1.0, importance))
            metadata = kwargs.get("metadata", {})
            metadata["user_id"] = self.user_id
            memory_id = self.manager.add_memory(
                content=content,
                memory_type=memory_type,
                importance=importance,
                metadata=metadata
            )
            return f"记忆已添加 (ID: {memory_id[:8]}, 类型: {memory_type})"
        except Exception as e:
            return f"添加记忆失败: {str(e)}"

    def _search_memory(
        self,
        query: str = "",
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
        min_importance: float = 0.0,
        **kwargs
    ) -> str:
        """
        搜索相关记忆
        """
        if not query:
            return "错误: 搜索查询不能为空"
        try:
            results = self.manager.retrieve_memories(
                query=query,
                limit=limit,
                memory_types=memory_types,
                min_importance=min_importance
            )
            if not results:
                return f"未找到与 '{query}' 相关的记忆"

            lines = [f"找到 {len(results)} 条相关记忆:"]
            type_labels = {
                "working": "工作记忆",
                "episodic": "情景记忆",
                "semantic": "语义记忆",
                "perceptual": "感知记忆"
            }
            for i, item in enumerate(results, 1):
                label = type_labels.get(item.memory_type, item.memory_type)
                preview = item.content[:60] + "..." if len(item.content) > 60 else item.content
                lines.append(f"{i}. [{label}] {preview} (重要性: {item.importance:.2f})")
            return "\n".join(lines)
        except Exception as e:
            return f"搜索记忆失败: {str(e)}"

    def _get_summary(self, limit: int = 10, **kwargs) -> str:
        """
        获取最近记忆摘要
        """
        try:
            if 'working' in self.manager.memory_types:
                working = self.manager.memory_types['working']
                items = sorted(working._items, key=lambda x: x.timestamp, reverse=True)[:limit]
                if items:
                    lines = ["最近记忆摘要:"]
                    for item in items:
                        lines.append(f"  {item.get_summary()}")
                    return "\n".join(lines)
            return "暂无记忆可摘要"
        except Exception as e:
            return f"获取摘要失败: {str(e)}"

    def _get_stats(self, **kwargs) -> str:
        """
        获取记忆系统统计信息
        """
        try:
            stats = self.manager.get_stats()
            lines = ["记忆系统统计:"]
            for key, value in stats.items():
                if isinstance(value, dict):
                    lines.append(f"  {key}:")
                    for k, v in value.items():
                        lines.append(f"    {k}: {v}")
                else:
                    lines.append(f"  {key}: {value}")
            return "\n".join(lines)
        except Exception as e:
            return f"获取统计失败: {str(e)}"

    def _update_memory(
        self,
        memory_id: str = "",
        content: Optional[str] = None,
        importance: Optional[float] = None,
        **kwargs
    ) -> str:
        """
        更新指定记忆
        """
        if not memory_id:
            return "错误: 需要提供 memory_id"
        try:
            updated = False
            for mem_type in self.manager.memory_types.values():
                if hasattr(mem_type, 'update'):
                    if mem_type.update(
                        memory_id,
                        content=content,
                        importance=importance,
                        user_id=self.user_id,
                    ):
                        updated = True
                        break
            if updated:
                return f"记忆 {memory_id[:8]} 已更新"
            else:
                return f"未找到记忆 {memory_id[:8]}"
        except Exception as e:
            return f"更新记忆失败: {str(e)}"

    def _remove_memory(self, memory_id: str = "", **kwargs) -> str:
        """
        删除指定记忆
        """
        if not memory_id:
            return "错误: 需要提供 memory_id"
        try:
            deleted = False
            for mem_type in self.manager.memory_types.values():
                if hasattr(mem_type, 'delete'):
                    if mem_type.delete(memory_id, user_id=self.user_id):
                        deleted = True
                        break
            if deleted:
                return f"记忆 {memory_id[:8]} 已删除"
            else:
                return f"未找到记忆 {memory_id[:8]}"
        except Exception as e:
            return f"删除记忆失败: {str(e)}"

    def _forget_memories(
        self,
        strategy: str = "importance_based",
        threshold: float = 0.1,
        max_age_days: int = 30,
        **kwargs
    ) -> str:
        """
        执行主动遗忘
        """
        try:
            report = self.manager.forget_memories(
                strategy=strategy,
                threshold=threshold,
                max_age_days=max_age_days
            )
            return f"已遗忘 {report.deleted_count} 条记忆 (策略: {strategy})"
        except Exception as e:
            return f"遗忘记忆失败: {str(e)}"

    def _consolidate_memories(
        self,
        from_type: str = "working",
        to_type: str = "episodic",
        importance_threshold: float = 0.7,
        **kwargs
    ) -> str:
        """
        记忆整合：将短期记忆提升为长期记忆
        """
        try:
            count = self.manager.consolidate_memories(
                from_type=from_type,
                to_type=to_type,
                importance_threshold=importance_threshold
            )
            return f"已整合 {count} 条记忆为长期记忆 ({from_type} → {to_type})"
        except Exception as e:
            return f"整合记忆失败: {str(e)}"

    def _clear_all(self, memory_type: Optional[str] = None, **kwargs) -> str:
        """
        清空记忆
        """
        try:
            count = self.manager.clear_all(memory_type=memory_type)
            return f"已清空 {count} 条记忆"
        except Exception as e:
            return f"清空记忆失败: {str(e)}"

    def _get_timeline(self, days: int = 30, limit: int = 10, **kwargs) -> str:
        """
        获取记忆时间线（按时间倒序浏览记忆）
        :param days: 最近多少天，默认 30 天
        :param limit: 返回最大条数
        :return: 格式化的时间线文本
        """
        try:
            results = self.manager.get_timeline(days=days, limit=limit)
            if not results:
                return f"最近 {days} 天内没有记忆"

            lines = [f"最近 {days} 天记忆时间线 (共 {len(results)} 条):"]
            for i, item in enumerate(results, 1):
                preview = item.content[:60] + "..." if len(item.content) > 60 else item.content
                lines.append(f"{i}. [{item.timestamp.strftime('%m-%d %H:%M')}] {preview}")
            return "\n".join(lines)
        except Exception as e:
            return f"获取时间线失败: {str(e)}"

    def _get_session(self, session_id: str = "", limit: int = 50, **kwargs) -> str:
        """
        获取指定会话的历史记忆
        :param session_id: 会话ID，为空则使用当前会话
        :param limit: 返回最大条数
        :return: 格式化的会话历史文本
        """
        try:
            sid = session_id or self.current_session_id or "default"
            results = self.manager.get_session_history(session_id=sid, limit=limit)
            if not results:
                return f"会话 {sid[:12]} 没有历史记录"

            lines = [f"会话 {sid[:12]} 历史 (共 {len(results)} 条):"]
            for i, item in enumerate(results, 1):
                preview = item.content[:80] + "..." if len(item.content) > 80 else item.content
                lines.append(f"{i}. {preview}")
            return "\n".join(lines)
        except Exception as e:
            return f"获取会话历史失败: {str(e)}"
