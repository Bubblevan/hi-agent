from .base import BaseLoader
from retrieval.models import Document
from pathlib import Path

class MarkitdownLoader(BaseLoader):
    """
    多格式统一加载器。内部委托给 markitdown 库转换，再走 MarkdownLoader 逻辑。

    支持格式（按扩展名分发）：
      - 文档: .pdf .docx .pptx .xlsx .html .xml
      - 图片: .png .jpg .jpeg .gif .bmp（OCR 提取文字）
      - 音频: .mp3 .wav .m4a（需要 whisper 提取转录文本）
      - 代码: .py .js .ts .go .rs .java 等（保留语法高亮的代码块）
      - 兜底: 所有未知格式尝试 markitdown 的通用转换

    输入：任意文件路径
    处理：
      1. 检测扩展名 → 选择转换策略
      2. markitdown 转换 → Markdown 字符串
      3. 把 Markdown 字符串当作"伪文件"交给 MarkdownLoader 的内联逻辑
      4. 附加原始格式信息到 metadata
    输出：Document
      - text = 转换后的 Markdown
      - metadata["source_format"] = 原始扩展名
      - metadata["converter"] = "markitdown"
    失败：
      - 不支持的格式 → ValueError
      - markitdown 转换失败 → RuntimeError（带原始错误信息）
    """

    # 格式 → 转换策略
    _MARKITDOWN_EXTENSIONS = {
        ".pdf", ".docx", ".pptx", ".xlsx",
        ".html", ".htm", ".xml", ".csv",
        ".json", ".epub",
    }

    _IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}

    _AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}

    _CODE_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".go", ".rs", ".java", ".c", ".cpp", ".h",
        ".sh", ".bash", ".yaml", ".yml", ".toml",
        ".sql", ".r", ".swift", ".kt",
    }

    def load(self, path: str | Path) -> Document:
        file_path = self._resolve(path)
        suffix = file_path.suffix.lower()

        # 1. 纯文本/代码 → 直接读，包装成 Markdown 代码块
        if suffix in self._CODE_EXTENSIONS:
            raw = self._try_read_text(file_path)
            lang = suffix.lstrip(".")
            text =f"```{lang}\n{raw}\n```"
            return self._build_document(
                source=file_path, text=text,
                source_format=suffix, converter="code-block",
            )

        # 2. Markdown → 委托给 MarkdownLoader
        if suffix == ".md":
            from retrieval.loaders.markdown import MarkdownLoader
            doc = MarkdownLoader().load(file_path)
            doc.metadata["source_format"] = ".md"
            doc.metadata["converter"] = "markdown"
            return doc

        # 3. 图片 → markitdown 内置 OCR（或后续接 paddleocr）
        if suffix in self._IMAGE_EXTENSIONS:
            return self._via_markitdown(file_path, source_format=suffix)

        # 4. 文档格式 → markitdown
        if suffix in self._MARKITDOWN_EXTENSIONS:
            return self._via_markitdown(file_path, source_format=suffix)

        # 5. 音频 → 暂不支持（需要 whisper，不是 markitdown 的职责）
        if suffix in self._AUDIO_EXTENSIONS:
            raise ValueError(
                f"音频文件暂不支持: {suffix}。"
                f"计划使用 whisper 提取转录文本，尚未实现。"
            )

        # 6. 兜底：未知格式也试一次 markitdown
        return self._via_markitdown(file_path, source_format=suffix)

    def _via_markitdown(self, file_path: Path, source_format: str) -> Document:
        """通过 markitdown 库转换为 Markdown，再包装为 Document。"""
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise ImportError("markitdown 未安装。pip install markitdown")

        md = MarkItDown()
        result = md.convert(str(file_path))
        return self._build_document(
            source=file_path,
            text=result.text_content,
            source_format=source_format,
            converter="markitdown",
        )

    def _build_document(
        self,
        *,
        source: Path,
        text: str,
        source_format: str,
        converter: str,
    ) -> Document:
        """统一的 Document 构造——所有转换路径最终都走这里。"""
        return Document.build(
user_id="default",
            namespace="default",
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
