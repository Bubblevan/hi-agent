# -----------------------------------------------------------------------------
# 模块定位：记忆系统持久化层 - SQLite 文档存储
# 架构位置：位于各记忆类型实现的底层，负责将结构化记忆数据落盘到本地 SQLite 数据库
# 设计分工：
#   - 结构化字段（内容、类型、时间、重要性、会话ID）：存在 SQLite，支持条件查询、排序、统计
#   - 向量嵌入数据：单独由向量数据库（如 Qdrant）存储，本表通过 embedding_id 关联
# 核心特性：
#   1. 零额外服务依赖：单文件数据库，开箱即用
#   2. 完整 CRUD + 条件查询 + 分页 + 统计能力
#   3. JSON 元数据字段：灵活扩展，无需修改表结构即可新增属性
#   4. 自动时间戳：创建/更新时间由数据库自动维护
#   5. 防 SQL 注入：全量参数化查询 + 排序字段白名单校验
# -----------------------------------------------------------------------------

import json
import sqlite3
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from pathlib import Path

class SQLiteDocumentStore:
    """
    SQLite 文档存储实现
    负责记忆结构化数据的持久化存储，支持按类型、会话、时间、重要性等多维度查询。
    与向量存储分层设计：本表存"元数据+文本内容"，向量库存"嵌入向量"，通过 ID 关联。
    """
    def __init__(self, db_path: str = "./memory_data/memory.db"):
        """
        初始化 SQLite 存储
        :param db_path: 数据库文件路径，支持相对路径/绝对路径
        """
        self.db_path = db_path
        db_dir = Path(db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化数据表（不存在则创建）
        self._init_tables()
        print(f"SQLite 文档存储初始化完成: {db_path}")

    def _get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接
        设计：每次操作新建连接、用完即释放，避免 SQLite 多线程不安全的问题
        配置 row_factory：让查询结果可以通过字段名访问，而非只能通过索引
        """
        conn = sqlite3.connect(self.db_path)
        # =====================================================================
        # 【语法详解：sqlite3.Row 行工厂】
        # =====================================================================
        # 1. 默认情况下，cursor.fetchone() 返回元组，只能通过下标 0/1/2 访问字段
        # 2. 设置 row_factory = sqlite3.Row 后，返回 Row 对象：
        #    - 可以像字典一样用 row["id"]、row["content"] 访问字段
        #    - 也可以用下标访问，兼容易用性和性能
        # 3. 配合 dict(row) 可直接转为标准 Python 字典
        # =====================================================================
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_tables(self):
        """
        初始化数据库表结构与索引
        幂等设计：使用 IF NOT EXISTS，重复执行不会报错
        """
        # =====================================================================
        # 【语法详解：with 上下文管理器 + SQLite 连接】
        # =====================================================================
        # 1. with 语句会自动管理资源：进入时获取连接，退出时自动关闭连接
        # 2. 对于 SQLite 连接，with 块同时管理事务：
        #    - 块内代码正常执行完 → 自动 commit 提交事务
        #    - 块内抛出异常 → 自动 rollback 回滚事务
        # 3. 避免手动写 try-except-commit-rollback 的样板代码
        # =====================================================================
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # ---------- 主表：记忆条目 ----------
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,          -- 记忆唯一ID，上层生成UUID，字符串类型
                    content TEXT NOT NULL,       -- 记忆文本内容
                    memory_type TEXT NOT NULL,   -- 记忆类型：working/episodic/semantic/perceptual
                    timestamp TEXT NOT NULL,     -- 业务时间戳（记忆发生时间），ISO格式字符串
                    importance REAL DEFAULT 0.5, -- 重要性评分 0.0~1.0
                    metadata TEXT,               -- 扩展元数据，JSON格式存储，结构灵活
                    embedding_id TEXT,           -- 预留：关联向量数据库中的向量ID
                    session_id TEXT,             -- 会话ID，按会话分组检索
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,  -- 记录创建时间，数据库自动生成
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP   -- 记录更新时间，触发器自动更新
                )
            """)

            # ---------- 索引设计：加速高频查询 ----------
            # 索引原则：只给经常出现在 WHERE/ORDER BY 中的字段建索引
            # 注意：索引会加快查询，但会减慢写入、占用磁盘，并非越多越好
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_type 
                ON memories(memory_type)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON memories(timestamp DESC)
            """)
            
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_session_id 
                ON memories(session_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_importance 
                ON memories(importance DESC)
            """)
            
            # ---------- 触发器：自动更新 updated_at 字段 ----------
            # 设计：每次更新记录时，自动把 updated_at 设为当前时间，无需业务代码维护
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS update_memories_updated_at
                AFTER UPDATE ON memories
                FOR EACH ROW
                BEGIN
                    UPDATE memories SET updated_at = CURRENT_TIMESTAMP
                    WHERE id = OLD.id;
                END;
            """)
            
            conn.commit()

    # ==========================================================
    # 核心 CRUD 操作
    # ==========================================================
    
    def insert(self, memory_id: str, content: str, memory_type: str,
               timestamp: Optional[datetime] = None,
               importance: float = 0.5,
               metadata: Optional[Dict[str, Any]] = None,
               embedding_id: Optional[str] = None,
               session_id: Optional[str] = None) -> bool:
        """
        插入一条记忆
        :param memory_id: 记忆唯一ID
        :param content: 记忆文本内容
        :param memory_type: 记忆类型
        :param timestamp: 业务时间戳，不传则使用当前时间
        :param importance: 重要性 0~1
        :param metadata: 扩展元数据字典
        :param embedding_id: 向量ID
        :param session_id: 会话ID
        :return: 是否插入成功
        """
        if timestamp is None:
            timestamp = datetime.now()

        # datetime 转 ISO 格式字符串，方便存储和排序
        timestamp_str = timestamp.isoformat()
        # 字典转 JSON 字符串存储；ensure_ascii=False 保证中文原样存储，不转义为 \uXXXX
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # =====================================================================
                # 【安全要点：参数化查询（? 占位符）】
                # =====================================================================
                # 1. 绝对禁止用字符串拼接 SQL，会导致 SQL 注入漏洞
                # 2. 使用 ? 作为占位符，参数通过第二个参数以元组形式传入
                # 3. SQLite 驱动会自动处理转义，完全杜绝注入风险
                # =====================================================================
                cursor.execute("""
                    INSERT INTO memories 
                    (id, content, memory_type, timestamp, importance, 
                     metadata, embedding_id, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (memory_id, content, memory_type, timestamp_str, 
                      importance, metadata_json, embedding_id, session_id))
                conn.commit()
                return True
        except sqlite3.IntegrityError:
            # 主键冲突：ID 已存在，插入失败
            return False
        except Exception as e:
            print(f"SQLite 插入失败: {e}")
            return False
    
    def get_by_id(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        根据 ID 查询单条记忆
        :param memory_id: 记忆ID
        :return: 记忆字典，不存在返回 None
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_dict(row)
            return None
        
    def query(
        self,
        memory_type: Optional[str] = None,
        session_id: Optional[str] = None,
        min_importance: float = 0.0,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "timestamp DESC"
    ) -> List[Dict[str, Any]]:
        """
        多条件组合查询记忆
        设计：动态拼接 WHERE 条件，未传入的条件不参与过滤
        :param memory_type: 按记忆类型过滤
        :param session_id: 按会话ID过滤
        :param min_importance: 最低重要性阈值
        :param start_time: 起始时间（含）
        :param end_time: 结束时间（含）
        :param limit: 每页条数
        :param offset: 分页偏移量
        :param order_by: 排序字段+方向
        :return: 记忆字典列表
        """
        conditions = []  # 存放 WHERE 条件片段
        params = []      # 存放对应参数值

        # 逐个判断参数，有值就加入条件
        if memory_type:
            conditions.append("memory_type = ?")
            params.append(memory_type)
        
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        
        if min_importance > 0:
            conditions.append("importance >= ?")
            params.append(min_importance)
        
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())
        
        # 拼接 WHERE 子句：没有条件就写 1=1 占位，保证 SQL 语法正确
        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # =====================================================================
        # 【安全要点：排序字段白名单校验】
        # =====================================================================
        # order_by 不能用参数化查询（? 只能传值，不能传字段名）
        # 因此用白名单机制：只允许指定的字段参与排序，非法值回退到默认排序
        # 彻底杜绝通过 order_by 参数进行 SQL 注入的可能
        # =====================================================================
        allowed_order_fields = ["timestamp", "importance", "created_at"]
        order_parts = order_by.split()
        if order_parts and order_parts[0] not in allowed_order_fields:
            order_by = "timestamp DESC"

        # 拼接最终 SQL
        query = f"""
            SELECT * FROM memories 
            WHERE {where_clause}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            # 批量转为字典
            return [self._row_to_dict(row) for row in rows]
        
    def update(
        self,
        memory_id: str,
        content: Optional[str] = None,
        importance: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        embedding_id: Optional[str] = None
    ) -> bool:
        """
        部分字段更新（只更新传入的字段，其他字段保持不变）
        设计：动态拼接 SET 子句，避免全量覆盖
        :param memory_id: 目标记忆ID
        :param content: 新内容，None 则不更新
        :param importance: 新重要性，None 则不更新
        :param metadata: 新元数据，None 则不更新
        :param embedding_id: 新向量ID，None 则不更新
        :return: 是否有记录被更新
        """
        updates = []  # SET 子句片段
        params = []   # 对应参数值
        
        if content is not None:
            updates.append("content = ?")
            params.append(content)
        
        if importance is not None:
            # 钳制到合法范围
            importance = max(0.0, min(1.0, importance))
            updates.append("importance = ?")
            params.append(importance)
        
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        
        if embedding_id is not None:
            updates.append("embedding_id = ?")
            params.append(embedding_id)
        
        # 没有要更新的字段，直接返回成功
        if not updates:
            return True
        
        # 手动更新 updated_at（与触发器双重保险）
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(memory_id)
        
        query = f"UPDATE memories SET {', '.join(updates)} WHERE id = ?"
        
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                # rowcount：受影响的行数，>0 表示更新成功
                return cursor.rowcount > 0
        except Exception as e:
            print(f"SQLite 更新失败: {e}")
            return False
        
    def delete(self, memory_id: str) -> bool:
        """
        根据 ID 删除单条记忆（硬删除）
        :param memory_id: 目标记忆ID
        :return: 是否有记录被删除
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"SQLite 删除失败: {e}")
            return False
        
    def delete_by_session(self, session_id: str) -> int:
        """
        批量删除某个会话的所有记忆
        :param session_id: 会话ID
        :return: 删除的记录条数
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM memories WHERE session_id = ?", (session_id,))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            print(f"SQLite 批量删除失败: {e}")
            return 0
        
    def clear(self, memory_type: Optional[str] = None) -> int:
        """
        清空记忆数据
        :param memory_type: 指定类型清空，None 则清空全表
        :return: 清空的记录条数
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if memory_type:
                    cursor.execute("DELETE FROM memories WHERE memory_type = ?", (memory_type,))
                else:
                    cursor.execute("DELETE FROM memories")
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            print(f"SQLite 清空失败: {e}")
            return 0
        
    def count(self, memory_type: Optional[str] = None) -> int:
        """
        统计记忆数量
        :param memory_type: 指定类型统计，None 则统计总数
        :return: 记录条数
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if memory_type:
                cursor.execute("SELECT COUNT(*) FROM memories WHERE memory_type = ?", (memory_type,))
            else:
                cursor.execute("SELECT COUNT(*) FROM memories")
            # COUNT 查询结果只有一行一列，取下标 0
            return cursor.fetchone()[0]
        
    def get_stats(self) -> Dict[str, Any]:
        """
        获取全量统计信息
        :return: 包含总数、各类型数量、平均重要性、时间范围的统计字典
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 总条数
            cursor.execute("SELECT COUNT(*) FROM memories")
            total = cursor.fetchone()[0]
            
            # 按类型分组统计
            cursor.execute("""
                SELECT memory_type, COUNT(*) as count 
                FROM memories 
                GROUP BY memory_type
            """)
            # =====================================================================
            # 【语法详解：字典推导式】
            # =====================================================================
            # 1. 格式：{key_expr: value_expr for item in iterable}
            # 2. 作用：一行代码从可迭代对象生成字典，替代循环+赋值的样板代码
            # 3. 本例等价于：
            #    by_type = {}
            #    for row in cursor.fetchall():
            #        by_type[row["memory_type"]] = row["count"]
            # =====================================================================
            by_type = {row["memory_type"]: row["count"] for row in cursor.fetchall()}
            
            # 平均重要性
            cursor.execute("SELECT AVG(importance) FROM memories")
            avg_importance = cursor.fetchone()[0] or 0.0
            
            # 最早和最晚的时间戳
            cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM memories")
            min_ts, max_ts = cursor.fetchone()
            
            return {
                "total": total,
                "by_type": by_type,
                "avg_importance": round(avg_importance, 3),
                "earliest": min_ts,
                "latest": max_ts,
                "db_path": self.db_path
            }
        
    # ==========================================================
    # 辅助方法
    # ==========================================================
    
    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """
        将 SQLite Row 对象转换为标准 Python 字典
        同时做字段类型转换：metadata 字段从 JSON 字符串反序列化为字典
        :param row: SQLite Row 对象
        :return: 结构化字典
        """
        result = dict(row)
        
        # 反序列化 metadata JSON 字段
        if result.get("metadata"):
            try:
                result["metadata"] = json.loads(result["metadata"])
            except json.JSONDecodeError:
                # JSON 解析失败则兜底为空字典，不抛出异常
                result["metadata"] = {}
        else:
            result["metadata"] = {}
        
        # 时间戳保持字符串格式：方便序列化、传输；调用方需要 datetime 可自行转换
        return result
    
    def __str__(self) -> str:
        """
        【魔法方法】自定义对象的字符串表示
        打印对象时会自动调用此方法，输出友好的描述信息
        """
        return f"SQLiteDocumentStore(path={self.db_path}, count={self.count()})"