import os
import math
import hashlib
from typing import List, Optional, Union
from abc import ABC, abstractmethod

# 尝试导入可选依赖（如果没有安装，会优雅降级）
try:
    from dashscope import TextEmbedding
    from dashscope.common.error import ApiError
    DASHSCOPE_AVAILABLE = True
except ImportError:
    DASHSCOPE_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    import numpy as np
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# ============================================================
# 1. 嵌入器抽象基类
# ============================================================
class BaseEmbedder(ABC):
    """
    所有嵌入器的统一抽象基类（接口契约）
    采用模板方法模式：定义了编码的通用流程（缓存逻辑），
    具体的向量生成算法交由子类实现 encode 方法。
    
    所有子类必须实现 encode 方法，保证对外调用方式完全一致。
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension  # 向量维度，对外统一承诺的输出形状
        self._cache = {}            # 内存缓存字典：key=文本哈希值，value=向量
        # 注：此处为简单字典缓存，生产环境可替换为 LRU 缓存限制内存占用
    
    @abstractmethod
    def encode(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        【抽象方法】文本向量化核心逻辑，由子类具体实现
        :param texts: 单个字符串或字符串列表
        :return: 二维浮点数列表，形状为 [文本数量, 向量维度]
        """
        pass

    def _get_cache_key(self, text: str) -> str:
        """
        生成缓存键：将长文本通过 MD5 映射为固定长度字符串
        设计原因：直接用长文本作为字典 key 内存开销大、哈希慢；
                 MD5 后长度固定，相同文本必然得到相同 key。
        :param text: 原始文本
        :return: 32 位 MD5 十六进制字符串
        """
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def encode_with_cache(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        带缓存的编码入口（推荐上层调用此方法）
        优化策略：先筛选出未缓存的文本，批量调用 encode 一次性计算，
                 再回填缓存并按原始顺序重组结果。
        为什么不逐个判断+逐个计算？因为批量调用 API / 模型推理的效率远高于单次。
        
        :param texts: 单个字符串或字符串列表
        :return: 与输入顺序一一对应的向量列表
        """

        # 统一输入格式：单字符串转为列表，后续逻辑统一处理
        if isinstance(texts, str):
            texts = [texts]

        results = []               # 存放 (索引, 向量) 元组，最后按索引排序
        uncached_texts = []        # 未命中缓存、需要实际计算的文本
        uncached_indices = []      # 对应文本在原始列表中的索引

        # 第一轮遍历：检查缓存，分离已缓存和未缓存的文本
        for i, text in enumerate(texts):
            key = self._get_cache_key(text)
            if key in self._cache:
                # 命中缓存，直接记录结果与原始索引
                results.append((i, self._cache[key]))
            else:
                # 未命中，加入待计算队列
                uncached_texts.append(text)
                uncached_indices.append(i)

        # 批量计算所有未缓存的文本（批量推理效率更高）
        if uncached_texts:
            new_vectors = self.encode(uncached_texts)
            # 回填缓存 + 加入结果集
            for idx, vec in zip(uncached_indices, new_vectors):
                key = self._get_cache_key(texts[idx])
                self._cache[key] = vec  # 写入缓存，下次直接复用
                results.append((idx, vec))

        # 按原始输入的索引排序，保证输出顺序与输入严格一致
        results.sort(key=lambda x: x[0])
        # 剥离索引，只返回向量
        return [vec for _, vec in results]
    
# ============================================================
# 2. 具体实现：DashScope（阿里云百炼云端嵌入）
# ============================================================
class DashScopeEmbedder(BaseEmbedder):
    """
    阿里云 DashScope 文本嵌入服务实现（第一优先级）
    优势：向量质量高、支持长文本、无需本地算力；
    劣势：依赖网络、需要 API Key、有调用成本。
    """

    def __init__(
        self, 
        api_key: Optional[str] = None,
        model: str = "text-embedding-v3",
        dimension: int = 1024  # text-embedding-v3 默认输出维度为 1024
    ):
        """
        初始化 DashScope 嵌入器
        :param api_key: API 密钥，优先级：传参 > 环境变量DASHSCOPE_API_KEY > 环境变量EMBED_API_KEY
        :param model: 嵌入模型名称，默认 text-embedding-v3
        :param dimension: 向量维度，需与所选模型匹配
        """
        super().__init__(dimension=dimension)
        self.model = model

        # 多级获取 API Key：支持代码传入、两种环境变量名，适配不同部署规范
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("EMBED_API_KEY")
        
        # 前置校验：无 Key 直接抛出，避免调用时才报错
        if not self.api_key:
            raise ValueError("DashScope API Key 未找到，请设置 DASHSCOPE_API_KEY 或 EMBED_API_KEY")
        
        # 前置校验：未安装 SDK 直接抛出
        if not DASHSCOPE_AVAILABLE:
            raise ImportError("❌ dashscope 库未安装，请运行: pip install dashscope")
        
        # 设置 SDK 全局密钥
        import dashscope
        dashscope.api_key = self.api_key
        
        print(f"DashScope 嵌入器已初始化 (模型: {self.model}, 维度: {self.dimension})")
    
    def encode(self, texts: List[str]) -> List[List[float]]:
        """
        调用 DashScope 官方 API 批量生成向量
        :param texts: 文本列表
        :return: 二维向量列表
        """
        # 空输入快速返回，避免无效 API 调用
        if not texts:
            return []
        
        try:
            # 调用文本嵌入接口
            # text_type 参数说明：
            #   - document：针对文档/知识库片段优化，适合检索场景的召回侧
            #   - query：针对用户查询优化，适合检索场景的查询侧
            response = TextEmbedding.call(
                model=self.model,
                input=texts,
                parameters={
                    "text_type": "document"
                }
            )
            # 请求成功，解析返回结果
            if response.status_code == 200:
                embeddings = []
                for item in response.output.get("embeddings", []):
                    embeddings.append(item.get("embedding", []))
                return embeddings
            else:
                raise Exception(f"API 调用失败: {response.status_code} - {response.message}")
        except Exception as e:
            raise RuntimeError(f"DashScope embedding failed: {e}") from e

# ============================================================
# 3. 具体实现：本地 Sentence-Transformers 模型
# ============================================================
class LocalTransformerEmbedder(BaseEmbedder):
    """
    本地 Sentence-Transformers 嵌入模型实现（第二优先级）
    优势：离线可用、无调用成本、延迟低；
    劣势：占用本地内存/显存、向量质量略低于云端大模型。
    """
    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        dimension: int = 384
    ):
        """
        初始化本地嵌入模型
        :param model_name: HuggingFace 模型名或本地模型路径
        :param dimension: 预期维度，实际以模型输出为准
        """
        super().__init__(dimension=dimension)
        self.model_name = model_name
        
        # 前置校验：依赖库是否安装
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("❌ sentence-transformers 库未安装，请运行: pip install sentence-transformers")
        
        try:
            # 加载模型（首次运行会自动下载到本地缓存目录）
            self.model = SentenceTransformer(model_name, local_files_only=True)
            
            # 实际维度校准：用测试文本推理一次，获取模型真实输出维度
            # 避免用户传入的 dimension 与模型实际维度不一致
            test_vec = self.model.encode("test")
            self.dimension = len(test_vec)
            print(f"本地嵌入器已初始化 (模型: {model_name}, 维度: {self.dimension})")
        except Exception as e:
            raise RuntimeError(f"加载本地模型失败: {e}")
    
    def encode(self, texts: List[str]) -> List[List[float]]:
        """
        使用本地模型批量编码文本
        :param texts: 文本列表
        :return: 二维向量列表
        """
        if not texts:
            return []
        try:
            # 批量推理
            # normalize_embeddings=True：对向量做 L2 归一化
            #   好处：归一化后余弦相似度 = 向量点积，计算更快，检索稳定性更好
            embeddings = self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False  # 关闭进度条，避免污染日志
            )
            
            # 统一输出格式：转为 Python 原生的 List[List[float]]
            # 兼容 numpy 数组、torch 张量等不同返回类型
            if hasattr(embeddings, "tolist"):
                embeddings = embeddings.tolist()
            else:
                embeddings = [list(vec) for vec in embeddings]

            # 保证批量维度：sentence-transformers 对单条输入会返回一维向量
            # 这里统一包装成二维列表，符合 BaseEmbedder 的接口契约
            if embeddings and not isinstance(embeddings[0], list):
                embeddings = [embeddings]

            return embeddings
        except Exception as e:
            raise RuntimeError(f"Local embedding failed: {e}") from e

# ============================================================
# 4. 兜底方案：TF-IDF 统计向量化
# ============================================================
class TFIDFEmbedder(BaseEmbedder):
    """
    基于 TF-IDF 的轻量级向量化（最终兜底方案）
    设计定位：在无网络、无深度学习库的极简环境下，仍能提供可用的向量生成能力。
    特点：无需外部模型、启动快、资源占用极低；
    局限：语义表达能力弱，仅保证向量维度合法与基础相似度区分度。
    
    字符级 N-gram 设计：
      使用 char 级分析而非分词，天然支持中文，无需额外引入分词器依赖。
    """
    def __init__(self, dimension: int = 384, max_features: int = 384):
        """
        初始化 TF-IDF 向量器
        :param dimension: 目标输出维度
        :param max_features: TF-IDF 最大特征词数量，控制向量维度上限
        """
        super().__init__(dimension=dimension)
        self.max_features = max_features
        
        if not SKLEARN_AVAILABLE:
            raise ImportError("❌ sklearn 库未安装，请运行: pip install scikit-learn")
        
        # 初始化 TF-IDF 向量生成器
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,    # 限制最大特征数，控制维度与内存
            stop_words=None,              # 不设停用词，兼容中英文混合场景
            analyzer='char',              # 字符级分析，天然支持中文，无需分词
            ngram_range=(1, 2)            # 同时提取 1 字和 2 字组合，提升表达能力
        )
        self._is_fitted = False  # 标记是否已完成词表拟合（TF-IDF 需要先拟合再转换）
        print(f"✅ TF-IDF 嵌入器已初始化 (维度: {self.dimension})")
    
    def encode(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """
        TF-IDF 向量化
        注：首次调用会基于输入文本拟合词表，后续调用沿用该词表
        :param texts: 文本或文本列表（自动处理单字符串）
        :return: 二维向量列表
        """
        # 统一为列表形式：单字符串自动包装成列表
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return []
        
        try:
            # 首次调用：用当前文本拟合词表（流式拟合，无需提前准备语料）
            if not self._is_fitted:
                self.vectorizer.fit(texts)
                self._is_fitted = True
            
            # 文本转 TF-IDF 稀疏矩阵
            sparse_matrix = self.vectorizer.transform(texts)
            
            # 转为密集矩阵（二维 numpy 数组）
            dense_vectors = sparse_matrix.toarray()
            
            # 维度对齐：保证输出维度严格等于 self.dimension
            current_dim = dense_vectors.shape[1]
            if current_dim < self.dimension:
                # 实际维度不足：尾部补零填充
                padded = []
                for vec in dense_vectors:
                    padded.append(list(vec) + [0.0] * (self.dimension - current_dim))
                return padded
            elif current_dim > self.dimension:
                # 实际维度超出：截断到目标维度
                return [list(vec[:self.dimension]) for vec in dense_vectors]
            else:
                # 维度一致：直接转换格式
                return [list(vec) for vec in dense_vectors]
                
        except Exception as e:
            # 终极兜底：TF-IDF 也失败时，用哈希法生成伪向量
            # 保证相同文本输出相同向量、维度正确，仅牺牲语义性
            print(f"TF-IDF 嵌入失败: {e}")
            return [self._hash_vector(text) for text in texts]
    
    def _hash_vector(self, text: str) -> List[float]:
        """
        纯哈希向量化（极端兜底方案）
        原理：利用 MD5 哈希的确定性，将文本映射为固定维度的数值向量，
             相同文本得到相同向量，不同文本近似随机分布。
        适用场景：所有依赖都不可用时，保证程序流程不中断。
        :param text: 输入文本
        :return: 归一化到 [-1, 1] 的浮点数向量
        """
        hash_bytes = hashlib.md5(text.encode('utf-8')).digest()
        vec = []
        for i in range(self.dimension):
            # 循环取哈希字节，映射到 [0, 1]，再平移到 [-1, 1]
            val = hash_bytes[i % len(hash_bytes)] / 255.0
            vec.append(val * 2 - 1)
        return vec

# ============================================================
# 5. 工厂函数：自动选择最佳嵌入器（核心降级入口）
# ============================================================
def get_text_embedder(
    provider: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key: Optional[str] = None,
    dimension: Optional[int] = None
) -> BaseEmbedder:
    """
    工厂函数：根据配置与环境自动选择并初始化嵌入器
    自动降级优先级：DashScope(云端) > LocalTransformer(本地模型) > TF-IDF(统计兜底)
    
    使用方式：
      1. auto 模式（默认）：按优先级逐级尝试，失败则自动降级，保证一定返回可用实例
      2. 指定 provider：强制使用某一种，失败则抛出异常
      
    :param provider: 嵌入提供方，可选 "dashscope" / "local" / "tfidf" / "auto"(默认)
    :param model_name: 模型名称，对应不同 provider 传入不同值
    :param api_key: API 密钥，仅 DashScope 需要
    :param dimension: 目标向量维度
    :return: BaseEmbedder 子类实例
    """
    
    # 从环境变量读取配置（支持通过环境变量全局配置，无需修改代码）
    env_provider = os.getenv("EMBED_PROVIDER") or os.getenv("EMBED_MODEL_TYPE")
    env_api_key = os.getenv("EMBED_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
    env_model = os.getenv("EMBED_MODEL_NAME")
    
    # 配置优先级：函数传参 > 环境变量 > 默认值 auto
    provider = provider or env_provider or "auto"
    
    # ---------- 第1级：尝试云端 DashScope ----------
    if provider in ["dashscope", "auto"]:
        try:
            embedder = DashScopeEmbedder(
                api_key=api_key or env_api_key,
                model=model_name or env_model or "text-embedding-v3",
                dimension=dimension or 1024
            )
            return embedder
        except Exception as e:
            print(f"DashScope 嵌入器初始化失败: {e}")
            if provider == "dashscope":
                # 强制指定 dashscope 但失败：直接抛出，不静默降级
                raise
            # auto 模式：打印警告，继续尝试下一级
    
    # ---------- 第2级：尝试本地 Sentence-Transformers ----------
    if provider in ["local", "auto"]:
        try:
            embedder = LocalTransformerEmbedder(
                model_name=model_name or env_model or "sentence-transformers/all-MiniLM-L6-v2",
                dimension=dimension or 384
            )
            return embedder
        except Exception as e:
            print(f"本地嵌入器初始化失败: {e}")
            if provider == "local":
                raise
            # auto 模式：继续降级
    
    # ---------- 第3级：兜底 TF-IDF ----------
    # 到达此处说明前两级都失败，或用户直接指定 tfidf
    print("降级到 TF-IDF 嵌入器（轻量级，无需外部依赖）")
    embedder = TFIDFEmbedder(dimension=dimension or 384)
    return embedder

# ============================================================
# 6. 全局单例工具（可选便捷方案）
# ============================================================
_global_embedder: Optional[BaseEmbedder] = None

def get_global_embedder() -> BaseEmbedder:
    """
    获取全局单例嵌入器
    设计目的：避免在程序多处重复初始化模型/连接，节省内存与初始化开销。
    适用场景：全局使用同一种嵌入配置的项目。
    注：如果需要多种不同配置的嵌入器，请自行实例化，不要使用此单例。
    :return: 全局唯一的 BaseEmbedder 实例
    """
    global _global_embedder
    if _global_embedder is None:
        _global_embedder = get_text_embedder()
    return _global_embedder
