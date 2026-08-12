"""
splitters/recursive.py

递归文本切分器 —— 基线实现。
适用于无标题结构的纯文本或代码块，按优先级逐步降级切分，
再根据 token 数量合并段落并加入重叠。
"""

from dataclasses import dataclass

from retrieval.models import Chunk, Document
from retrieval.splitters.base import SplitterParams


@dataclass(frozen=True)
class _Span:
    start: int
    end: int


class RecursiveSplitter:
    """
    递归字符切分器。

    使用预定义的优先级分隔符列表，从粗粒度到细粒度逐级拆分文本，
    直到每个片段的估算 token 数 <= chunk_size 或分隔符耗尽。
    最后将所有片段合并为 chunk_size token 数的块，并在块间生成重叠。

    构造参数：
        params: SplitterParams 对象，也可用关键字参数直接传入 chunk_size / chunk_overlap。
    """

    def __init__(self, params: SplitterParams | None = None, **kwargs):
        if params is None:
            params = SplitterParams(**kwargs)
        self.chunk_size = params.chunk_size          # 目标 chunk token 数
        self.chunk_overlap = params.chunk_overlap    # 相邻 chunk 重叠 token 数
        self.token_counter = params.token_counter

    def split(self, document: Document) -> list[Chunk]:
        """主入口：将文档切成 Chunk 列表"""
        # 第一步：递归切分为不超过 token 预算的原始片段
        splits = self._split_text(document.text, 0, self._get_separators())
        # 第二步：基于 token 数合并片段，生成 Chunk 对象
        chunks = self._merge_splits(splits, document)
        return chunks

    def _get_separators(self) -> list[str]:
        """
        返回切分优先级列表。
        顺序：先按双换行（段落），再按单换行（行），再按中文句号、英文句号，
        最后按空格硬切。
        """
        return ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " "]

    def _split_text(self, text: str, offset: int, separators: list[str]) -> list[_Span]:
        """
        递归拆分文本。

        策略：
        1. 从 separators 中找到第一个实际出现在 text 中的分隔符。
        2. 若找不到，或分隔符列表已空，退化为按字符硬切。
        3. 按该分隔符切分，对每个片段检查长度：
           - 若片段 token 数 <= chunk_size，直接保留；
           - 否则，用剩余的更细粒度的分隔符列表递归切分该片段；
           - 若没有更细粒度的分隔符，按字符边界寻找满足 token 预算的切点。
        """
        if not text:
            return []
        if self.token_counter.count(text) <= self.chunk_size:
            return [_Span(offset, offset + len(text))]

        for index, separator in enumerate(separators):
            if separator not in text:
                continue
            spans: list[_Span] = []
            cursor = 0
            while cursor < len(text):
                found = text.find(separator, cursor)
                end = len(text) if found < 0 else found + len(separator)
                if end > cursor:
                    part = text[cursor:end]
                    spans.extend(self._split_text(part, offset + cursor, separators[index + 1 :]))
                cursor = end
            if len(spans) > 1:
                return spans

        return self._hard_split(text, offset)

    def _hard_split(self, text: str, offset: int) -> list[_Span]:
        """Split at character boundaries while enforcing the configured unit."""
        spans: list[_Span] = []
        start = 0
        while start < len(text):
            end = start + 1
            while end <= len(text) and self.token_counter.count(text[start:end]) <= self.chunk_size:
                end += 1
            end = max(start + 1, end - 1)
            spans.append(_Span(offset + start, offset + end))
            start = end
        return spans

    def _merge_splits(self, splits: list[_Span], document: Document) -> list[Chunk]:
        """
        将原始片段合并为最终 chunk，控制 token 数并加入重叠。

        流程：
        1. 遍历所有片段，累计当前 chunk 的 token 数。
        2. 如果当前 chunk 加入新片段后 token 数 <= chunk_size，则加入。
        3. 否则，产出当前 chunk（调用 Chunk.build），然后处理重叠：
           - 从当前 chunk 的末尾向前选取片段，使得选取片段的 token 总数 <= chunk_overlap，
             这些片段作为下一个 chunk 的前缀。
        4. 将当前片段（触发溢出的那个）加入新 chunk。
        5. 循环结束后产出最后一个 chunk。

        参数:
            splits: 原始文本片段列表
            document: 原始文档对象

        返回:
            List[Chunk] 对象
        """
        chunks: list[Chunk] = []
        current_chunk_splits: list[_Span] = []
        current_tokens = 0                     # 当前 chunk 的 token 数
        position = 0                           # chunk 序号

        for split in splits:
            split_tokens = self.token_counter.count(document.text[split.start:split.end]) or 1

            # 如果当前 chunk 为空，或加入后仍不超限，则直接加入
            if current_tokens + split_tokens <= self.chunk_size or not current_chunk_splits:
                current_chunk_splits.append(split)
                current_tokens += split_tokens
            else:
                # 当前 chunk 已满，需要产出
                # Span 保留原始分隔符和偏移，直接从原文截取即可。
                start = current_chunk_splits[0].start
                end = current_chunk_splits[-1].end
                content = document.text[start:end]
                chunks.append(
                    Chunk.build(
                        document=document,
                        content=content,
                        position=position,
                        start_char=start,
                        end_char=end,
                    )
                )
                position += 1

                # ---- 重叠处理 ----
                if self.chunk_overlap > 0 and current_chunk_splits:
                    kept: list[_Span] = []
                    kept_tokens = 0
                    # 从当前 chunk 的末尾向前选取片段，直到达到 overlap token 数
                    for s in reversed(current_chunk_splits):
                        t = self.token_counter.count(document.text[s.start:s.end]) or 1
                        if kept_tokens + t > self.chunk_overlap:
                            break
                        kept.append(s)
                        kept_tokens += t
                    current_chunk_splits = list(reversed(kept))
                    current_tokens = kept_tokens
                    while (
                        current_chunk_splits
                        and current_tokens + split_tokens > self.chunk_size
                    ):
                        removed = current_chunk_splits.pop(0)
                        current_tokens -= (
                            self.token_counter.count(
                                document.text[removed.start:removed.end]
                            )
                            or 1
                        )
                else:
                    current_chunk_splits = []
                    current_tokens = 0

                # 将当前溢出的 split 加入新 chunk
                current_chunk_splits.append(split)
                current_tokens += split_tokens

        # 处理最后一个 chunk
        if current_chunk_splits:
            start = current_chunk_splits[0].start
            end = current_chunk_splits[-1].end
            content = document.text[start:end]
            chunks.append(
                Chunk.build(
                    document=document,
                    content=content,
                    position=position,
                    start_char=start,
                    end_char=end,
                )
            )

        return chunks
