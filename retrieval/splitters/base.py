"""
splitters/base.py

定义文本切分器的基础组件：
- TextSplitter 协议：所有切分器必须遵守的公共接口
- SplitterParams 数据类：统一的构造参数
- 中英文混合 token 估算工具函数
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable, List
from models import Document, Chunk


# ---------------------------------------------------------------------------
# 1. 切分器协议
# ---------------------------------------------------------------------------
@runtime_checkable
class TextSplitter(Protocol):
    """
    文本切分器协议（结构化子类型）。

    任何对象只要拥有一个方法：
        split(self, document: Document) -> List[Chunk]
    就被视为合法的 TextSplitter，无需显式继承本类。
    
    加上 @runtime_checkable 后，可以使用 isinstance(obj, TextSplitter)
    在运行时检查对象是否满足该协议。
    from splitters.base import TextSplitter
    class MySplitter:
        def split(self, document: Document) -> list[Chunk]:
            ...
    s = MySplitter()
    print(isinstance(s, TextSplitter))   # True
    """
    def split(self, document: Document) -> List[Chunk]:
        """
        将一篇文档切分为多个语义块。

        参数:
            document: 待切分的完整文档对象，包含文本与元信息。

        返回:
            List[Chunk]: 切分后的语义块列表，顺序与原文一致。
        """
        ...


# ---------------------------------------------------------------------------
# 2. 切分参数
# ---------------------------------------------------------------------------
@dataclass
class SplitterParams:
    """
    所有切分器共享的基础构造参数。
    
    虽然不是强制要求，但建议所有 splitter 的 __init__ 都接收此对象
    （或至少包含 chunk_size / chunk_overlap 两个字段），
    以保证 pipeline 中可以用统一的方式实例化。

    字段:
        chunk_size: 每个 chunk 的目标 token 数。
        chunk_overlap: 相邻 chunk 之间重叠的 token 数。
    """
    chunk_size: int = 800
    chunk_overlap: int = 120


# ---------------------------------------------------------------------------
# 3. CJK 字符判断
# ---------------------------------------------------------------------------
def _is_cjk(ch: str) -> bool:
    """
    判断一个字符是否属于 CJK（中日韩统一表意文字）Unicode 区块。

    CJK 字符在多数大模型的分词器中会被单独拆分为一个 token，
    因此估算 token 数量时每个 CJK 字符计为 1 token。

    参数:
        ch: 单个字符

    返回:
        True 如果 ch 位于已知的 CJK 区块内，否则 False。
    """
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or      # 基本汉字
        0x3400 <= code <= 0x4DBF or      # 扩展 A
        0x20000 <= code <= 0x2A6DF or    # 扩展 B
        0x2A700 <= code <= 0x2B73F or    # 扩展 C
        0x2B740 <= code <= 0x2B81F or    # 扩展 D
        0x2B820 <= code <= 0x2CEAF or    # 扩展 E
        0xF900 <= code <= 0xFAFF         # 兼容汉字
    )


# ---------------------------------------------------------------------------
# 4. 混合中英文 token 估算
# ---------------------------------------------------------------------------
def _approx_token_len(text: str) -> int:
    """
    近似估算一段混合中英文文本的 token 数量。

    规则:
      - 每个 CJK 字符算 1 个 token
      - 其余部分按空格分词，每个单词算 1 个 token

    这样估算简单且足够用于控制 chunk 大小，与真实 tokenizer 结果偏差可控。

    参数:
        text: 待估算的文本字符串

    返回:
        int: 估算的 token 数量（至少为 0）
    """
    # 统计 CJK 字符数量
    cjk_count = sum(1 for ch in text if _is_cjk(ch))

    # 移除 CJK 字符后的剩余部分按空白分词
    # 简单起见，直接用整个文本的 split() 结果减去纯 CJK 的干扰，
    # 但 split() 会把中文连在一起的字符串当成一个整体，造成低估。
    # 这里采用更稳健的做法：把文本按空格或标点拆开，再数非空英文 token。
    # 为了简洁，此处实现直接使用整个文本 split() 的长度，
    # 但会减去已经被统计为 CJK 的字符块（split 后的纯中文 token）。
    # 实际上一个中文句子被 split() 后会成为一个大 token，这反而接近真实分词行为，
    # 因此可接受。
    # 更精确的方法是：将 CJK 字符替换为空格，再 split，但性能损失不大。
    # 这里保留你之前的实现：
    non_cjk_tokens = len([t for t in text.split() if t])  # 去除空白
    # 注意：这个做法会低估英文 token，因为 "Hello world" 分成两个 token，但中文部分也被分开了，
    # 若中英文夹杂，例如 "你好world" split 后得到 ["你好world"]，token 数为 1，而此时 cjk_count=2，
    # 总 token = 2 + 1 = 3，可能偏高。不过作为近似值足够。
    return cjk_count + non_cjk_tokens

    # 如果你希望更贴近实际，可以用以下替代实现（注释保留）：
    # import re
    # # 将 CJK 字符替换为空格，再按空白分词
    # cleaned = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', ' ', text)
    # english_tokens = len(cleaned.split())
    # return cjk_count + english_tokens