# -----------------------------------------------------------------------------
# 模块定位：记忆系统向量存储层 - Qdrant 实现
# 架构分工：
#   - SQLiteDocumentStore：存结构化文本/元数据，负责条件过滤、排序、统计
#   - QdrantVectorStore：存向量嵌入，负责语义相似度检索
#   两者通过 memory_id 一一关联，共同完成"向量召回 + 元数据过滤"的混合检索
# 核心特性：
#   1. 双模式支持：本地 Docker 部署 / Qdrant 云服务，自动识别连接方式
#   2. 优雅降级：库未安装、连接失败时自动标记不可用，上层退化为关键词检索
#   3. 幂等操作：集合自动创建、upsert 幂等写入，重复调用不报错
#   4. 过滤检索：支持按元数据字段过滤，实现按记忆类型、会话ID等条件的向量检索
# -----------------------------------------------------------------------------

import os
import uuid
from typing import List, Dict, Any, Optional, Tuple

# =============================================================================
# 【设计模式：可选依赖 + 优雅降级】
# =============================================================================
# 用 try-except 探测依赖是否安装，用全局布尔变量标记可用性
# 好处：不强制用户安装 qdrant-client，不需要向量检索的场景可直接使用兜底方案
# 同类设计在 embedding.py 中也有使用，是"多层降级"架构的基础手段
# =============================================================================
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    print("Qdrant 库未安装，向量检索将降级。安装: pip install qdrant-client")

class QdrantVectorStore:
    """
    Qdrant 向量存储实现类
    负责向量的增删查，支持按元数据过滤的相似度检索
    所有操作都做了异常兜底：Qdrant 不可用时返回空/False，上层业务无感降级
    """
    
    def __init__(
        self,
        collection_name: str = "hello_agents_vectors",
        vector_size: int = 384,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        host: str = "localhost",
        port: int = 6333
    ):
        """
        初始化 Qdrant 向量存储
        :param collection_name: 集合名称，类似关系型数据库的表
        :param vector_size: 向量维度，必须与嵌入器输出维度一致
        :param url: Qdrant 云服务地址，传了则走云端模式
        :param api_key: 云服务 API 密钥
        :param host: 本地服务地址，默认 localhost
        :param port: 本地服务端口，默认 6333
        """
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.client = None          # Qdrant 客户端实例
        self._initialized = False   # 初始化成功标记，供上层判断可用性
        
# 前置检查：库都没装，直接跳过连接逻辑
        if not QDRANT_AVAILABLE:
            print("Qdrant 未安装，向量存储不可用")
            return
        
        try:
            # 多级读取配置：传参 > 环境变量 > 默认值
            url = url or os.getenv("QDRANT_URL")
            api_key = api_key or os.getenv("QDRANT_API_KEY")
            
            if url:
                # 云端模式：通过 URL + API Key 连接 Qdrant Cloud
                self.client = QdrantClient(url=url, api_key=api_key)
                print(f"Qdrant 云服务连接成功: {url}")
            else:
                # 本地模式：连接本地 Docker 部署的 Qdrant 服务
                self.client = QdrantClient(host=host, port=port)
                print(f"Qdrant 本地服务连接成功: {host}:{port}")
            
            # 确保集合存在，不存在则自动创建
            self._ensure_collection()
            self._initialized = True

        except Exception as e:
            # 连接失败兜底：打印警告，标记为不可用，不抛出异常中断主程序
            print(f"Qdrant 连接失败: {e}")
            self.client = None
            self._initialized = False

    def _ensure_collection(self):
        """
        幂等初始化集合
        集合类似关系型数据库的表，每个集合存储相同维度的向量
        距离度量选择 COSINE（余弦相似度），与嵌入模型输出匹配，检索效果最好
        """
        if not self.client:
            return
        
        # 获取所有已有集合列表
        collections = self.client.get_collections().collections
        
        # =====================================================================
        # 【语法详解：any() + 生成器表达式】
        # =====================================================================
        # 1. any(iterable)：判断可迭代对象中是否至少有一个为 True，有则返回 True
        # 2. 生成器表达式：(c.name == self.collection_name for c in collections)
        #    逐个产出布尔值，不生成完整列表，节省内存
        # 3. 等价写法：
        #    exists = False
        #    for c in collections:
        #        if c.name == self.collection_name:
        #            exists = True
        #            break
        # 4. 优势：一行完成判断，代码简洁，遇到第一个匹配就停止遍历（短路求值）
        # =====================================================================
        exists = any(c.name == self.collection_name for c in collections)

        if not exists:
            # 创建集合，指定向量维度和距离计算方式
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_size,
                    distance=Distance.COSINE  # 余弦距离，值越小越相似，最终返回的 score 是相似度
                )
            )
            print(f"Qdrant 集合 '{self.collection_name}' 已创建 (维度: {self.vector_size})")
        else:
            print(f"Qdrant 集合 '{self.collection_name}' 已存在")
    
    def is_available(self) -> bool:
        """
        检查向量存储是否可用
        上层业务调用此方法判断是否走向量检索，不可用则降级到关键词检索
        """
        return self._initialized and self.client is not None
    
    def add_vector(
        self,
        vector: List[float],
        memory_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        添加一条向量（幂等 upsert）
        :param vector: 嵌入向量列表
        :param memory_id: 关联的记忆 ID，用于和 SQLite 文档存储关联
        :param metadata: 附加元数据，可用于检索时过滤
        :return: 是否添加成功
        """
        if not self.is_available():
            return False
        
        try:
            # 生成向量点的唯一 ID（UUID 字符串）
            point_id = str(uuid.uuid4())
            
            # =====================================================================
            # 【语法详解：字典解包 **】
            # =====================================================================
            # 1. **dict 会把字典的键值对展开到外层字典中
            # 2. 本例中：{"memory_id": memory_id, **(metadata or {})}
            #    等价于先写 memory_id 字段，再把 metadata 里的所有键值对合并进来
            # 3. 好处：不用循环 update，一行完成字典合并
            # 4. 注意：如果有重复 key，后面的会覆盖前面的；这里 metadata 不会包含 memory_id
            # =====================================================================
            self.client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=point_id,
                        vector=vector,
                        payload={
                            "memory_id": memory_id,
                            ** (metadata or {})
                        }
                    )
                ]
            )
            return True
        except Exception as e:
            print(f"Qdrant 添加向量失败: {e}")
            return False
    
    def search_vectors(
        self,
        query_vector: List[float],
        limit: int = 10,
        score_threshold: Optional[float] = None,
        filter_payload: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        向量相似度检索
        :param query_vector: 查询向量
        :param limit: 返回最相似的条数
        :param score_threshold: 相似度阈值，低于此值的结果被过滤
        :param filter_payload: 元数据过滤条件，如 {"memory_type": "episodic"}
        :return: 结果列表，每项包含 memory_id、相似度分数、完整 payload
        """
        if not self.is_available():
            return []
        
        try:
            # 构建过滤条件
            q_filter = None
            if filter_payload:
                conditions = []
                # 遍历过滤字典，每个键值对转成一个 FieldCondition
                for key, value in filter_payload.items():
                    conditions.append(
                        FieldCondition(key=key, match=MatchValue(value=value))
                    )
                if conditions:
                    # must 表示所有条件都要满足（AND 关系）
                    q_filter = Filter(must=conditions)
            
            # 执行向量搜索
            search_result = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector,
                limit=limit,
                score_threshold=score_threshold,
                query_filter=q_filter
            )
            
            # 格式化返回结果：把 Qdrant 对象转成普通字典，上层无需依赖 Qdrant 类型
            results = []
            for hit in search_result:
                results.append({
                    "memory_id": hit.payload.get("memory_id", hit.id),
                    "score": hit.score,
                    "payload": hit.payload
                })
            return results
            
        except Exception as e:
            print(f"Qdrant 搜索失败: {e}")
            return []
        
    def delete_by_memory_id(self, memory_id: str) -> bool:
        """
        根据关联的记忆 ID 删除对应向量
        设计说明：Qdrant 不支持直接按 payload 字段删除，所以分两步：
          1. 用 scroll 按 memory_id 过滤查出所有对应的点 ID
          2. 再按点 ID 批量删除
        :param memory_id: 关联的记忆 ID
        :return: 是否执行成功
        """
        if not self.is_available():
            return False
        
        try:
            # scroll：按过滤条件遍历查询点，返回 (点列表, 下一页游标)
            points = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[FieldCondition(key="memory_id", match=MatchValue(value=memory_id))]
                ),
                limit=100
            )
            # points[0] 是匹配到的点列表，points[1] 是分页游标
            if points and points[0]:
                # 从点对象列表中提取所有 id，组成新的列表
                point_ids = [p.id for p in points[0]]
                if point_ids:
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=point_ids
                    )
            return True
        except Exception as e:
            print(f"Qdrant 删除失败: {e}")
            return False
        
    def clear(self) -> int:
        """
        清空所有向量（删除集合后重建）
        选择删集合重建而非逐条删除，性能更高、更彻底
        :return: 成功返回 1，失败返回 0
        """
        if not self.is_available():
            return 0
        
        try:
            self.client.delete_collection(self.collection_name)
            self._ensure_collection()  # 重建空集合
            return 1
        except Exception as e:
            print(f"Qdrant 清空失败: {e}")
            return 0