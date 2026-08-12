"""
splitters/markdown.py

Markdown 标题感知分块器。
利用 Markdown 的标题层级（#、##、###）进行语义切分，
保证 chunk 的 heading_path 信息完整，并在切分时保持代码块、列表等结构的完整。
"""

import re
from typing import Any

from retrieval.models import Chunk, Document
from retrieval.splitters.base import SplitterParams


_ATX_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


class MarkdownSplitter:
    """
    Markdown 语义分块器。

    工作流程：
    1. 按标题和空行将文档分解为段落（paragraph），每个段落记录其所属的标题路径（heading_path）。
    2. 基于 token 数合并段落为 chunk，并在 chunk 间加入重叠。
    3. 为每个 chunk 指定最深层非空的 heading_path 作为其标题定位。

    构造参数：同 SplitterParams。
    """

    def __init__(self, params: SplitterParams | None = None, **kwargs):
        if params is None:
            params = SplitterParams(**kwargs)
        self.chunk_size = params.chunk_size
        self.chunk_overlap = params.chunk_overlap
        self.token_counter = params.token_counter

    def split(self, document: Document) -> list[Chunk]:
        """
        主入口：将 Markdown 文档切割为 Chunk 列表。
        """
        # 第一阶段：结构解析 —— 将全文切分为带标题路径的段落
        paragraphs = self._split_paragraphs_with_headings(document.text)
        # 第二阶段：段落合并 —— 按 token 数合并为 chunk（含重叠）
        raw_chunks = self._chunk_paragraphs(paragraphs)
        # 第三阶段：对象化 —— 生成不可变 Chunk 对象，position 由 enumerate 自动分配
        return [
            Chunk.build(
                document=document,
                content=rc["content"],
                position=i,
                start_char=rc["start"],
                end_char=rc["end"],
                heading_path=rc.get("heading_path"),
            )
            for i, rc in enumerate(raw_chunks)
        ]

    def _split_paragraphs_with_headings(self, text: str) -> list[dict[str, Any]]:
        """
        按标题和空行将文本分解为段落。

        处理逻辑：
        - 遍历每一行。
        - 遇到标题行（以 '#' 开头）：
            1. 先将当前缓冲区的内容作为一个段落输出（flush）。
            2. 解析标题层级（# 的数量）和标题文本。
            3. 更新标题栈：弹出所有层级 >= 当前层级的标题，然后将新标题压入。
        - 遇到空行：触发 flush，生成一个段落。
        - 普通行：加入缓冲区。
        - 文件结束时 flush 剩余内容。

        返回的每个段落是一个字典，包含：
            "content": 段落文本（去除首尾空白）
            "heading_path": 如 "# 系统设计 > ### 缓存策略"，若不在任何标题下则为 None
            "start": 段落起始字符位置（相对于原文）
            "end": 段落结束字符位置
        """
        lines = text.splitlines(keepends=True)
        heading_stack: list[str] = []
        paragraphs: list[dict[str, Any]] = []
        buf: list[str] = []
        buf_start = 0
        char_pos = 0                    # 当前已扫描的字符位置（包含换行符）
        fence: tuple[str, int] | None = None

        def flush_buf(end_pos: int):
            """将缓冲区中的行合并为一个段落并添加到 paragraphs，然后清空缓冲区"""
            nonlocal buf, buf_start
            if not buf:
                return
            raw_content = "".join(buf)
            leading = len(raw_content) - len(raw_content.lstrip())
            content = raw_content.strip()
            if content:
                start = buf_start + leading
                paragraphs.append({
                    "content": content,
                    "heading_path": " > ".join(heading_stack) if heading_stack else None,
                    "start": start,
                    "end": start + len(content),
                })
            buf = []

        for ln in lines:
            raw = ln.rstrip("\r\n")
            fence_match = _FENCE_RE.match(raw)
            if fence_match:
                marker = fence_match.group(1)
                if fence is None:
                    fence = (marker[0], len(marker))
                elif marker[0] == fence[0] and len(marker) >= fence[1]:
                    fence = None

            heading_match = None if fence is not None or fence_match else _ATX_HEADING_RE.match(raw)
            if heading_match:
                flush_buf(char_pos)
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                heading_stack[level - 1 :] = []
                heading_stack.append(title)
                char_pos += len(ln)
                continue

            if not buf:
                buf_start = char_pos
            if raw.strip() == "" and fence is None:
                flush_buf(char_pos)
            else:
                buf.append(ln)

            char_pos += len(ln)

        # 处理文件末尾的内容
        flush_buf(char_pos)

        # 如果没有任何段落（例如空文档），返回全文作为一个无标题段落
        if not paragraphs:
            paragraphs = [{
                "content": text,
                "heading_path": None,
                "start": 0,
                "end": len(text),
            }]
        return paragraphs

    def _chunk_paragraphs(self, paragraphs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        基于 token 数合并段落为 chunk，并加入重叠。

        流程：
        1. 遍历段落列表。
        2. 如果当前 chunk 加入新段落后 token 数 <= chunk_size，或 chunk 为空，则加入。
        3. 否则，产出当前 chunk，然后根据 chunk_overlap 保留末尾若干段落作为重叠。
        4. 将溢出的段落放入新 chunk。
        5. 循环结束后产出最后一个 chunk。

        每个 chunk 的 heading_path 取值策略：
        从该 chunk 包含的段落中，由后向前查找第一个有 heading_path 的段落，
        使用其 heading_path。这代表了该 chunk 内容的最深层标题位置。
        （注意：如果 chunk 跨标题合并，可能有偏差，但在博客/文档场景下概率较低）

        返回的每个原始 chunk 字典包含：
            "content": 合并后的文本
            "start": 起始字符位置
            "end": 结束字符位置
            "heading_path": 标题路径（可能为 None）
        """
        paragraphs = [
            piece
            for paragraph in paragraphs
            for piece in self._fit_paragraph(paragraph)
        ]
        chunks: list[dict[str, Any]] = []
        cur: list[dict[str, Any]] = []
        cur_tokens = 0                # 当前累积段落的 token 总数
        i = 0

        while i < len(paragraphs):
            p = paragraphs[i]
            p_tokens = self.token_counter.count(p["content"]) or 1

            # 如果可以加入当前 chunk
            if cur_tokens + p_tokens <= self.chunk_size or not cur:
                cur.append(p)
                cur_tokens += p_tokens
                i += 1
            else:
                # 产出当前 chunk
                content = "\n\n".join(x["content"] for x in cur)
                start = cur[0]["start"]
                end = cur[-1]["end"]
                # 取最后一个有 heading_path 的段落
                heading_path = next(
                    (x["heading_path"] for x in reversed(cur) if x.get("heading_path")),
                    None
                )
                chunks.append({
                    "content": content,
                    "start": start,
                    "end": end,
                    "heading_path": heading_path,
                })

                # ---- 重叠处理 ----
                if self.chunk_overlap > 0 and cur:
                    kept: list[dict[str, Any]] = []
                    kept_tokens = 0
                    # 从后往前选取段落，累计 token 数不超过 overlap
                    for x in reversed(cur):
                        t = self.token_counter.count(x["content"]) or 1
                        if kept_tokens + t > self.chunk_overlap:
                            break
                        kept.append(x)
                        kept_tokens += t
                    cur = list(reversed(kept))
                    cur_tokens = kept_tokens
                    while cur and cur_tokens + p_tokens > self.chunk_size:
                        removed = cur.pop(0)
                        cur_tokens -= self.token_counter.count(removed["content"]) or 1
                else:
                    cur = []
                    cur_tokens = 0

        # 产出最后一个 chunk
        if cur:
            content = "\n\n".join(x["content"] for x in cur)
            start = cur[0]["start"]
            end = cur[-1]["end"]
            heading_path = next(
                (x["heading_path"] for x in reversed(cur) if x.get("heading_path")),
                None
            )
            chunks.append({
                "content": content,
                "start": start,
                "end": end,
                "heading_path": heading_path,
            })

        return chunks

    def _fit_paragraph(self, paragraph: dict[str, Any]) -> list[dict[str, Any]]:
        """Hard-split an oversized paragraph while retaining source offsets."""
        content = paragraph["content"]
        if self.token_counter.count(content) <= self.chunk_size:
            return [paragraph]

        pieces: list[dict[str, Any]] = []
        start = 0
        while start < len(content):
            end = start + 1
            while (
                end <= len(content)
                and self.token_counter.count(content[start:end]) <= self.chunk_size
            ):
                end += 1
            end = max(start + 1, end - 1)
            pieces.append({
                **paragraph,
                "content": content[start:end],
                "start": paragraph["start"] + start,
                "end": paragraph["start"] + end,
            })
            start = end
        return pieces
