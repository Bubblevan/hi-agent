# -----------------------------------------------------------------------------
# 模块定位：感知记忆（Perceptual Memory）具体实现
# 设计对标：人类认知模型中的感知记忆 —— 存储多模态感知输入（图像、音频、视频、文本等原始感知信息）
# 核心能力：
#   1. 多模态全覆盖：支持文本、图像、音频、视频四大类，可扩展自定义编码器
#   2. 三级编码降级：自定义编码器 → 内置标准编码器 → 文本描述嵌入兜底
#   3. 双存储架构：SQLite 存元数据与描述 + Qdrant 存多模态向量，支持跨模态检索
#   4. 智能模态推断：根据文件扩展名自动识别模态，无需手动指定
#   5. 轻量预览：小文件存 base64 预览，大文件仅存哈希引用，避免数据库膨胀
# 设计模式：策略模式 —— 不同模态对应不同编码策略，支持插拔式替换
# -----------------------------------------------------------------------------

import os
import base64
import hashlib
from typing import List, Dict, Any, Optional, Union
from datetime import datetime
import math

from ..base import MemoryItem, MemoryConfig, BaseMemory
from ..embedding import BaseEmbedder
from ..storage.document import SQLiteDocumentStore
from ..storage.qdrant import QdrantVectorStore

# ============================================================
# 1. 模态类型常量定义
# ============================================================
# 统一管理所有支持的模态类型，消除魔法字符串，便于全局引用与后续扩展
MODALITY_TYPES = {
    "text": "text",
    "image": "image",
    "audio": "audio",
    "video": "video",
    "other": "other"
}

# ============================================================
# 2. 感知记忆类
# ============================================================
class PerceptualMemory(BaseMemory):
    """
    感知记忆实现类
    定位：多模态感知信息的长期存储，保存图像、音频、视频等非文本内容及其描述
    存储介质：SQLite（元数据、文本描述、文件引用） + Qdrant（多模态向量，支持跨模态检索）
    检索方式：文本查询跨模态检索（优先），降级为关键词匹配检索
    业务场景：多模态对话记忆、图片/音频回忆、视觉/听觉信息沉淀
    """
    
    def __init__(
        self,
        config: MemoryConfig,
        embedder: BaseEmbedder,
        custom_encoders: Optional[Dict[str, Any]] = None
    ):
        """
        初始化感知记忆
        :param config: 全局记忆配置对象
        :param embedder: 文本嵌入器，用于降级场景下的文本编码与检索
        :param custom_encoders: 自定义多模态编码器字典，支持用户注入自己的模型
            格式示例：
            {
                "image": clip_encode_func,   # 图像编码器
                "audio": clap_encode_func,   # 音频编码器
                "video": video_encode_func   # 视频编码器
            }
            函数签名要求：接收文件路径/字节数据，返回一维向量列表 List[float]
        """
        super().__init__(config)
        self.text_embedder = embedder  # 文本嵌入器，作为兜底编码与检索入口
        self.custom_encoders = custom_encoders or {}

        # 第一层：SQLite 文档存储，保存元数据、文本描述、文件引用
        self.store = SQLiteDocumentStore(config.database_path)
        
        # 第二层：Qdrant 向量存储，保存多模态向量，支持跨模态相似度检索
        self.vector_store = QdrantVectorStore(
            collection_name=config.qdrant_collection or "perceptual_vectors",
            vector_size=embedder.dimension,  # 所有模态向量统一维度，保证可检索
            url=config.qdrant_url,
            api_key=config.qdrant_api_key
        )

        self._use_vector = self.vector_store.is_available()
        
        # 逐个检查各模态编码器是否就绪，记录状态
        self._encoders_ready = {}
        for modality in MODALITY_TYPES.values():
            self._encoders_ready[modality] = self._check_encoder_ready(modality)
        
        mode = "向量检索" if self._use_vector else "关键词检索"
        print(f"感知记忆已初始化 (模式: {mode})")

        ready_mods = [m for m, r in self._encoders_ready.items() if r]
        if ready_mods:
            print(f"可用模态编码器: {', '.join(ready_mods)}")
        else:
            print("警告：没有多模态编码器，将使用文本降级")

    def _check_encoder_ready(self, modality: str) -> bool:
        """
        检查指定模态的编码器是否可用
        检查优先级：自定义编码器 > 内置标准编码器
        采用依赖探测模式：通过 try-except 导入判断库是否安装，不强制依赖
        :param modality: 模态类型
        :return: 是否就绪
        """
        # 1. 优先检查用户注入的自定义编码器
        if modality in self.custom_encoders:
            return True
        
        # 2. 尝试探测内置依赖是否安装
        try:
            if modality == "image":
                # 探测 CLIP 多模态模型库是否可用
                import clip
                return True
            elif modality == "audio":
                # 探测 librosa 音频处理库是否可用
                import librosa
                return True
            else:
                # 视频/其他模态暂无内置编码器
                return False
        except ImportError:
            return False
        
    def _encode_modality(self, modality: str, data: Union[str, bytes], file_path: Optional[str] = None) -> Optional[List[float]]:
        """
        多模态数据编码核心方法
        三级降级策略：
          1. 自定义编码器：用户注入的优先级最高，完全由用户控制
          2. 内置标准编码器：图像用 CLIP，音频用 MFCC 特征
          3. 文本兜底：将文件名/数据描述转为文本，用文本嵌入器编码，保证任何情况都能输出向量
        :param modality: 模态类型
        :param data: 数据内容，文本字符串或原始字节
        :param file_path: 本地文件路径，优先级高于 data 参数
        :return: 一维向量列表，编码失败返回 None
        """
        # ---------- 第一级：自定义编码器 ----------
        if modality in self.custom_encoders:
            try:
                encoder = self.custom_encoders[modality]
                # 优先传文件路径，其次传字节数据，最后传文本内容
                if file_path:
                    return encoder(file_path)
                elif isinstance(data, bytes):
                    return encoder(data)
                else:
                    return encoder(data)
            except Exception as e:
                print(f"警告：自定义编码器失败 ({modality}): {e}")
                # 自定义失败不中断，继续降级到内置方案

        # ---------- 第二级：内置标准编码器 ----------
        if modality == "image":
            try:
                import clip
                import torch
                from PIL import Image
                import io  # 处理内存字节流
                
                # 自动选择设备：有 GPU 用 CUDA，没有用 CPU
                device = "cuda" if torch.cuda.is_available() else "cpu"
                # 加载 CLIP 模型与图像预处理函数
                model, preprocess = clip.load("ViT-B/32", device=device)
                
                # 加载图片：优先本地文件，其次内存字节流
                if file_path and os.path.exists(file_path):
                    image = preprocess(Image.open(file_path)).unsqueeze(0).to(device)
                else:
                    # =====================================================================
                    # 【语法详解：io.BytesIO 内存文件对象】
                    # =====================================================================
                    # 1. 作用：将 bytes 二进制数据包装成类文件对象，供需要文件输入的 API 使用
                    # 2. 场景：不需要落盘，直接在内存中处理图片/音频等二进制数据
                    # 3. 本例：把 raw_data 字节流包装后传给 PIL.Image.open，无需写入临时文件
                    # =====================================================================
                    image = preprocess(Image.open(io.BytesIO(data))).unsqueeze(0).to(device)
                
                # 推理生成图像特征向量，关闭梯度节省显存
                with torch.no_grad():
                    image_features = model.encode_image(image)
                    # 张量 → numpy 数组 → 扁平化 → Python 原生列表
                    vector = image_features.cpu().numpy().flatten().tolist()
                return vector
            except Exception as e:
                print(f"警告：CLIP 图像编码失败: {e}")
        
        elif modality == "audio":
            try:
                import librosa
                import numpy as np
                import io
                
                # 加载音频：优先文件，其次字节流，统一重采样到 16kHz
                if file_path and os.path.exists(file_path):
                    y, sr = librosa.load(file_path, sr=16000)
                else:
                    y, sr = librosa.load(io.BytesIO(data), sr=16000)
                
                # 提取 MFCC 梅尔频率倒谱系数（音频领域经典特征）
                mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
                # 对时间维度取均值，得到固定长度的特征向量
                vector = np.mean(mfcc, axis=1).tolist()
                
                # =====================================================================
                # 维度对齐设计
                # 不同编码器输出维度可能不同，为了统一存入向量库，必须对齐到文本嵌入器的维度
                # 维度不足尾部补零，维度超出头部截断，保证检索时维度完全匹配
                # =====================================================================
                target_dim = self.text_embedder.dimension
                if len(vector) < target_dim:
                    vector.extend([0.0] * (target_dim - len(vector)))
                elif len(vector) > target_dim:
                    vector = vector[:target_dim]
                return vector
            except Exception as e:
                print(f"警告：音频特征编码失败: {e}")
        
        # ---------- 第三级：文本兜底编码 ----------
        # 所有编码器都不可用时，生成文本描述，用文本嵌入器编码
        if file_path:
            text = f"{modality}文件: {os.path.basename(file_path)}"
        else:
            # 文本数据取前100字符，二进制数据给通用描述
            text = f"{modality}数据: {data[:100] if isinstance(data, str) else '二进制数据'}"
        
        try:
            return self.text_embedder.encode(text)[0]
        except Exception:
            return None
        
    # ==========================================================
    # 核心 CRUD 接口实现
    # ==========================================================
    
    def add(
        self,
        memory_item: MemoryItem,
        file_path: Optional[str] = None,
        modality: Optional[str] = None,
        raw_data: Optional[bytes] = None
    ) -> str:
        """
        添加一条感知记忆
        执行流程：
          1. 自动推断模态（未指定时）
          2. 封装元数据：模态、文件路径、数据哈希、小文件预览
          3. 生成多模态向量
          4. 写入 SQLite 主存储
          5. 向量可用时写入 Qdrant
        :param memory_item: 标准记忆条目，content 字段存该感知内容的文本描述
        :param file_path: 关联的本地文件路径
        :param modality: 手动指定模态，不传则自动推断
        :param raw_data: 原始二进制数据，无需落盘时直接传内存字节
        :return: 记忆 ID
        """
        # 1. 模态识别：手动指定优先，否则根据文件/数据自动推断
        if modality is None:
            if file_path:
                modality = self._infer_modality(file_path)
            elif raw_data:
                modality = "other"  # 原始字节无法推断类型，归为 other
            else:
                modality = "text"

        # 2. 封装元数据
        metadata = memory_item.metadata or {}
        metadata["modality"] = modality
        if file_path:
            metadata["file_path"] = file_path
        if raw_data:
            # =====================================================================
            # 【设计考量：大文件不入库原则】
            # 原始二进制数据体积大，直接存入 SQLite 会导致数据库膨胀、读写性能下降
            # 因此只存 MD5 哈希用于唯一性校验，10KB 以下的小文件可存 base64 预览
            # 大文件建议由外部对象存储/文件系统管理，此处仅保留引用路径
            # =====================================================================
            file_hash = hashlib.md5(raw_data).hexdigest()
            metadata["data_hash"] = file_hash
            # 小文件存 base64 预览，方便快速查看
            if len(raw_data) < 10240:  # 10KB 阈值
                # =====================================================================
                # 【语法详解：base64 编码】
                # =====================================================================
                # 1. base64.b64encode(bytes)：将二进制数据编码为 ASCII 可打印的 base64 字节
                # 2. .decode('utf-8')：将字节转为字符串，方便存入 JSON 元数据
                # 3. 用途：把二进制图片/音频转成文本格式，嵌入到数据库字段中
                # =====================================================================
                metadata["preview_base64"] = base64.b64encode(raw_data).decode('utf-8')
        
        # 3. 生成多模态向量
        vector = None
        if self._use_vector:
            try:
                if file_path:
                    vector = self._encode_modality(modality, None, file_path=file_path)
                elif raw_data:
                    vector = self._encode_modality(modality, raw_data)
                else:
                    # 纯文本描述，走文本编码
                    vector = self._encode_modality("text", memory_item.content)
            except Exception as e:
                print(f"警告：向量编码失败: {e}")

        # 4. 写入 SQLite 主存储
        session_id = metadata.get("session_id", "default")
        success = self.store.insert(
            memory_id=memory_item.id,
            content=memory_item.content,
            memory_type="perceptual",
            timestamp=memory_item.timestamp,
            importance=memory_item.importance,
            metadata=metadata,
            session_id=session_id,
            user_id=memory_item.user_id
        )
        if not success:
            raise RuntimeError(f"感知记忆存储失败: {memory_item.id}")
        
        # 5. 同步写入向量库
        if vector and self._use_vector:
            self.vector_store.add_vector(
                vector=vector,
                memory_id=memory_item.id,
                metadata={
                    "memory_type": "perceptual",
                    "user_id": memory_item.user_id,
                    "modality": modality,
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
        modality: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs
    ) -> List[MemoryItem]:
        """
        检索感知记忆（支持模态过滤）
        核心特性：跨模态检索 —— 用户输入文本描述，可检索匹配的图像/音频等内容
        降级策略：向量检索失败自动降级为关键词匹配
        :param query: 文本查询描述
        :param limit: 返回最大条数
        :param min_importance: 最低重要性阈值
        :param modality: 指定只检索某类模态
        :param session_id: 按会话过滤
        :return: 按相关性排序的记忆列表
        """
        # ----- 方案 A：向量跨模态检索（优先） -----
        if self._use_vector:
            try:
                # 用文本嵌入生成查询向量，和多模态向量做相似度计算
                query_vector = self.text_embedder.encode(query)[0]
                
                # 构造过滤条件
                filter_payload = {"memory_type": "perceptual"}
                if modality:
                    filter_payload["modality"] = modality
                if session_id:
                    filter_payload["session_id"] = session_id
                
                results = self.vector_store.search_vectors(
                    query_vector=query_vector,
                    limit=limit * 2,
                    score_threshold=0.2,  # 感知模态相似度阈值稍低，适配跨模态差异
                    filter_payload=filter_payload
                )
                if results:
                    memory_items = []
                    for r in results:
                        mem_id = r["memory_id"]
                        doc = self.store.get_by_id(mem_id)
                        if doc and doc["importance"] >= min_importance:
                            item = MemoryItem(
                                id=doc["id"],
                                user_id=doc.get("user_id", "default_user"),
                                content=doc["content"],
                                memory_type="perceptual",
                                timestamp=datetime.fromisoformat(doc["timestamp"]),
                                importance=doc["importance"],
                                metadata=doc.get("metadata", {})
                            )
                            # 保存向量相似度分数到元数据，便于调试
                            item.metadata["vector_score"] = r["score"]
                            item.metadata["relevance_score"] = r["score"]
                            memory_items.append(item)
                    # =====================================================================
                    # 【语法详解：lambda 匿名函数 + sorted 排序】
                    # =====================================================================
                    # 1. 作用：按记忆的 importance 属性进行降序排序
                    # 2. key=lambda x: x.importance 表示：取列表每个元素的 importance 属性作为排序依据
                    # 3. reverse=True 表示降序，重要性高的排在前面
                    # 4. 等价完整写法：
                    #    def get_importance(item):
                    #        return item.importance
                    #    memory_items.sort(key=get_importance, reverse=True)
                    # 5. 设计说明：此处用重要性做二次排序，也可改为按 vector_score 排序，
                    #    当前设计兼顾语义相似度与知识重要性，避免低重要性的高相似度结果排在前面
                    # =====================================================================
                    memory_items.sort(
                        key=lambda x: x.metadata.get("relevance_score", 0.0),
                        reverse=True,
                    )
                    return memory_items[:limit]
            except Exception as e:
                print(f"警告：向量检索失败，降级关键词: {e}")

        # ----- 方案 B：关键词检索（兜底降级） -----
        candidates = self.store.query(
            memory_type="perceptual",
            user_id=kwargs.get("user_id"),
            session_id=session_id,
            min_importance=min_importance,
            limit=limit * 3,
            order_by="importance DESC"
        )
        
        if not candidates:
            return []
        
        # 按指定模态过滤候选集
        if modality:
            # 列表推导式 + 字典嵌套取值，筛选出匹配模态的条目
            candidates = [c for c in candidates if c.get("metadata", {}).get("modality") == modality]
        
        # 关键词评分 + 重要性加权 + 文件额外加分
        scored = []
        for cand in candidates:
            score = self._keyword_match(query, cand["content"])
            # 有文件路径的条目加少量额外权重（完整文件比纯描述更有价值）
            extra = 0.1 if cand.get("metadata", {}).get("file_path") else 0.0
            final_score = score * 0.6 + cand["importance"] * 0.3 + extra
            scored.append((final_score, cand))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # 转为标准 MemoryItem 对象
        results = []
        for _, cand in scored[:limit]:
            item = MemoryItem(
                id=cand["id"],
                user_id=cand.get("user_id", "default_user"),
                content=cand["content"],
                memory_type="perceptual",
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
        更新感知记忆
        支持更新文本描述、重要性，也支持更新关联的文件/原始数据（同步更新向量）
        :param memory_id: 目标记忆 ID
        :param content: 新的文本描述
        :param importance: 新的重要性
        :param kwargs: 可传 file_path、raw_data、modality 等参数更新文件数据
        :return: 是否更新成功
        """
        file_path = kwargs.get("file_path")
        raw_data = kwargs.get("raw_data")
        modality = kwargs.get("modality")
        
        # 第一步：更新 SQLite 主数据
        success = self.store.update(
            memory_id=memory_id,
            content=content,
            importance=importance,
            metadata=kwargs.get("metadata"),
            user_id=user_id
        )
        
        # 第二步：如果更新了文件/数据，同步删除旧向量并生成新向量
        if success and (file_path or raw_data) and self._use_vector:
            try:
                self.vector_store.delete_by_memory_id(memory_id, user_id=user_id)
                
                # 获取最新的元数据
                doc = self.store.get_by_id(memory_id)
                if doc:
                    meta = doc.get("metadata", {})
                    mod = modality or meta.get("modality", "text")
                    
                    if file_path:
                        vector = self._encode_modality(mod, None, file_path=file_path)
                    elif raw_data:
                        vector = self._encode_modality(mod, raw_data)
                    else:
                        vector = None
                    
                    if vector:
                        self.vector_store.add_vector(
                            vector=vector,
                            memory_id=memory_id,
                            metadata={
                                "memory_type": "perceptual",
                                "user_id": doc.get("user_id", "default_user"),
                                "modality": mod,
                                "importance": doc["importance"],
                                "session_id": meta.get("session_id", "default")
                            }
                        )
            except Exception as e:
                print(f"警告：更新向量失败: {e}")
        
        return success
    
    def delete(self, memory_id: str, user_id: Optional[str] = None) -> bool:
        """
        删除单条感知记忆（双存储同步删除）
        :param memory_id: 目标记忆 ID
        :return: 是否删除成功
        """
        success = self.store.delete(memory_id, user_id=user_id)
        if success and self._use_vector:
            self.vector_store.delete_by_memory_id(memory_id, user_id=user_id)
        return success
    
    def clear(self, user_id: Optional[str] = None) -> int:
        """
        清空所有感知记忆（双存储同步清空）
        :return: 被清空的记录条数
        """
        count = self.store.clear(memory_type="perceptual", user_id=user_id)
        if self._use_vector:
            filter_payload = {"memory_type": "perceptual"}
            if user_id:
                filter_payload["user_id"] = user_id
            self.vector_store.clear(filter_payload=filter_payload)
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取感知记忆统计信息
        :return: 统计字典
        """
        stats = self.store.get_stats()
        return {
            "type": "perceptual",
            "count": stats["by_type"].get("perceptual", 0),
            "total": stats["total"],
            "avg_importance": stats["avg_importance"],
            "vector_mode": "Qdrant" if self._use_vector else "SQLite (降级)",
            "db_path": stats["db_path"]
        }
    
    # ==========================================================
    # 内部辅助方法
    # ==========================================================
    
    def _infer_modality(self, file_path: str) -> str:
        """
        根据文件扩展名自动推断模态类型
        :param file_path: 文件路径
        :return: 模态类型字符串
        """
        # =====================================================================
        # 【语法详解：os.path.splitext】
        # =====================================================================
        # 1. 作用：拆分文件路径为 (文件名主体, 扩展名) 元组
        # 2. 示例：os.path.splitext("cat.jpg") → ("cat", ".jpg")
        # 3. 取索引 [1] 得到扩展名，转小写后匹配后缀列表
        # =====================================================================
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
            return 'image'
        elif ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a']:
            return 'audio'
        elif ext in ['.mp4', '.avi', '.mov', '.mkv', '.webm']:
            return 'video'
        elif ext in ['.txt', '.md', '.pdf', '.docx']:
            return 'text'
        else:
            return 'other'
        
    def _keyword_match(self, query: str, content: str) -> float:
        """
        关键词匹配得分（正则分词 + 词集重叠率）
        与其他记忆类型保持一致的算法，保证跨模块行为统一
        :param query: 查询文本
        :param content: 待匹配内容
        :return: 匹配得分 0~1
        """
        import re
        if not query or not content:
            return 0.0
        q_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', query.lower()))
        c_words = set(re.findall(r'[\w\u4e00-\u9fa5]+', content.lower()))
        if not q_words:
            return 0.0
        overlap = len(q_words & c_words)
        return min(1.0, overlap / len(q_words))
    
    def __str__(self) -> str:
        """
        【魔法方法】自定义对象字符串表示
        打印对象时自动调用，直观展示记忆条数与向量检索开关状态
        """
        return f"PerceptualMemory(count={self.store.count('perceptual')}, vector={'ON' if self._use_vector else 'OFF'})"
    
    
