"""
splitters/recursive.py

递归文本切分器 —— 基线实现。
适用于无标题结构的纯文本或代码块，按优先级逐步降级切分，
再根据 token 数量合并段落并加入重叠。
"""

from typing import List
from models import Document, Chunk
from splitters.base import TextSplitter, SplitterParams, _approx_token_len

class RecursiveSplitter:
    """
    递归字符切分器。

    使用预定义的优先级分隔符列表，从粗粒度到细粒度逐级拆分文本，
    直到每个片段长度 <= chunk_size（字符数限制）或分隔符耗尽。
    最后将所有片段合并为 chunk_size token 数的块，并在块间生成重叠。

    构造参数：
        params: SplitterParams 对象，也可用关键字参数直接传入 chunk_size / chunk_overlap。
    """
    def __init__(self, params: SplitterParams | None = None, **kwargs):
        if params is None:
            params = SplitterParams(**kwargs)
        self.chunk_size = params.chunk_size          # 目标 chunk token 数
        self.chunk_overlap = params.chunk_overlap    # 相邻 chunk 重叠 token 数

    def split(self, document: Document) -> List[Chunk]:
        """主入口：将文档切成 Chunk 列表"""
        # 第一步：递归切分为原始片段（每个片段文本长度 <= chunk_size 字符）
        splits = self._split_text(document.text, self._get_separators())
        # 第二步：基于 token 数合并片段，生成 Chunk 对象
        chunks = self._merge_splits(splits, document)
        return chunks

    def _get_separators(self) -> List[str]:
        """
        返回切分优先级列表。
        顺序：先按双换行（段落），再按单换行（行），再按中文句号、英文句号，
        最后按空格硬切。
        """
        return ["\n\n", "\n", "。", ".", " "]
    
    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """
        递归拆分文本。

        策略：
        1. 从 separators 中找到第一个实际出现在 text 中的分隔符。
        2. 若找不到，或分隔符列表已空，退化为按字符硬切。
        3. 按该分隔符切分，对每个片段检查长度：
           - 若片段长度 <= chunk_size（字符数），直接保留；
           - 否则，用剩余的更细粒度的分隔符列表递归切分该片段；
           - 若没有更细粒度的分隔符，直接按字符硬切。
        """
        final_splits = []
        # 选择实际可用的最粗粒度分隔符
        separator = separators[-1]  # 默认使用最细粒度
        for sep in separators:
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                break

        # 按选定分隔符切分
        if separator:
            # 保留分隔符本身：使用 split(sep) 会丢失分隔符，这里直接 split 不保留，
            # 但为了之后还原位置，我们记录 split 结果，并在合并时处理字符位置。
            # 对于递归 splitter，简单采用 split 即可。
            splits = text.split(separator)
        else:
            # 无可用分隔符，按字符硬切
            splits = list(text)

        # 构建剩余的分隔符列表（去除当前选用的那个）
        new_separators = []
        for s in separators:
            if s == separator:
                break
            new_separators.append(s)
        # 移除第一个元素（即当前分隔符）
        new_separators = new_separators[1:] if new_separators else []

        for split in splits:
            if len(split) <= self.chunk_size:
                final_splits.append(split)
            elif new_separators:
                # 还有更细粒度的分隔符，递归切分
                final_splits.extend(self._split_text(split, new_separators))
            else:
                # 最后手段：直接按字符硬切（每 chunk_size 字符一段）
                for i in range(0, len(split), self.chunk_size):
                    final_splits.append(split[i:i + self.chunk_size])
        return final_splits
    
    