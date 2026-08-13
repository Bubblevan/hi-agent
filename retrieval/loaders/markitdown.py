"""
retrieval/loaders/markitdown.py

多格式统一加载器。
内部委托给 markitdown 库将各种格式转换为 Markdown，再封装为 Document。
对于纯代码文件，直接包装为 Markdown 代码块；对于音频等暂不支持的格式，报错提示。
"""

from pathlib import Path
from typing import Union

from .base import BaseLoader
from retrieval.models import Document


class MarkitdownLoader(BaseLoader):
    """
    多格式统一加载器。

    支持格式（可通过注册表扩展）：
      - 文档类: .pdf .docx .pptx .xlsx .html .xml .epub 等 → markitdown 转换
      - 图片类: .png .jpg .jpeg .gif .bmp .webp → markitdown（内部可能使用 OCR）
      - 代码类: .py .js .ts .go .java 等 → 直接封装为 Markdown 代码块
      - Markdown: .md → 委托给 MarkdownLoader 处理
      - 音频类: .mp3 .wav 等 → 暂不支持（计划用 whisper 转录）
      - 兜底: 未知格式也尝试用 markitdown 转换

    用法:
        loader = MarkitdownLoader()
        doc = loader.load(
            "/path/to/file.pdf", user_id="alice", namespace="papers"
        )
    """

    # ---- 格式分类 ----
    # markitdown 可原生转换的文档格式
    _MARKITDOWN_EXTENSIONS = {
        ".pdf", ".docx", ".pptx", ".xlsx",
        ".html", ".htm", ".xml", ".csv",
        ".json", ".epub",
    }

    # 图片格式（markitdown 会尝试 OCR，如需更好效果可替换为 paddleocr）
    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

    # 音频格式（暂不支持，预留）
    _AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

    # 代码文件格式（按扩展名映射到 Markdown 代码块的语言标识）
    _CODE_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".go", ".rs", ".java", ".c", ".cpp", ".h",
        ".sh", ".bash", ".yaml", ".yml", ".toml",
        ".sql", ".r", ".swift", ".kt",
    }

    def load(
        self,
        path: Union[str, Path],
        *,
        user_id: str,
        namespace: str,
    ) -> Document:
        """
        加载文件，根据扩展名分派到不同的处理逻辑，最终返回 Document。
        """
        self._validate_tenant_context(user_id=user_id, namespace=namespace)
        file_path = self._resolve(path)
        suffix = file_path.suffix.lower()

        # 1. 代码文件：直接读取原文并包装为 Markdown 代码块
        if suffix in self._CODE_EXTENSIONS:
            raw = self._try_read_text(file_path)
            lang = suffix.lstrip(".")
            text = f"```{lang}\n{raw}\n```"
            return self._build_document(
                source=file_path, text=text,
                source_format=suffix, converter="code-block",
                user_id=user_id, namespace=namespace,
            )

        # 2. Markdown 文件：委托给专门的 MarkdownLoader（保留其元数据处理逻辑）
        if suffix == ".md":
            from retrieval.loaders.markdown import MarkdownLoader
            return MarkdownLoader().load(
                file_path, user_id=user_id, namespace=namespace
            )

        # 3. 图片：使用 markitdown（内置 OCR 或外部库）
        if suffix in self._IMAGE_EXTENSIONS:
            return self._via_markitdown(file_path, suffix, user_id, namespace)

        # 4. 文档格式：使用 markitdown 转换
        if suffix in self._MARKITDOWN_EXTENSIONS:
            return self._via_markitdown(file_path, suffix, user_id, namespace)

        # 5. 音频：暂不支持，给出明确错误信息和未来计划
        if suffix in self._AUDIO_EXTENSIONS:
            raise ValueError(
                f"音频文件暂不支持: {suffix}。"
                f"计划使用 whisper 转录文本，但尚未实现。"
            )

        # 6. 兜底：未知格式也尝试用 markitdown 转换
        return self._via_markitdown(file_path, suffix, user_id, namespace)

    def _via_markitdown(
        self, file_path: Path, source_format: str, user_id: str, namespace: str
    ) -> Document:
        """
        通过 markitdown 库将文件转换为 Markdown，再包装为 Document。

        参数:
            file_path: 文件路径
            source_format: 原始扩展名（用于记录）

        返回:
            Document 对象，其 text 为转换后的 Markdown
        """
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise ImportError(
                "markitdown 未安装，请执行: pip install markitdown"
            )

        md = MarkItDown()
        result = md.convert(str(file_path))
        return self._build_document(
            source=file_path,
            text=result.text_content,
            source_format=source_format,
            converter="markitdown",
            user_id=user_id,
            namespace=namespace,
        )

    def _build_document(
        self,
        *,
        source: Path,
        text: str,
        source_format: str,
        converter: str,
        user_id: str,
        namespace: str,
    ) -> Document:
        """
        统一的 Document 构造方法——所有转换路径最终都汇聚于此。

        保证 metadata 字段规范：
          - loader: "markitdown" （用于 pipeline 选择 splitter）
          - file_name: 原始文件名
          - file_size: 文件字节数
          - source_format: 原始扩展名（如 ".pdf"）
          - converter: 实际使用的转换器名称
        """
        return Document.build(
            user_id=user_id,
            namespace=namespace,
            source=str(source),
            text=text,
            metadata={
                "loader": "markitdown",
                "file_name": source.name,
                "file_size": source.stat().st_size,
                "source_format": source_format,
                "converter": converter,
            },
        )
