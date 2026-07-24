from .base import BaseLoader
from retrieval.models import Document
from pathlib import Path

class TextLoader(BaseLoader):
    """纯文本加载器。UTF-8 → GBK 降级。"""

    def load(self, path: str | Path) -> Document:
        file_path = self._resolve(path)
        text = self._try_read_text(file_path)

        return Document.build(
            user_id="default",        # 调用方后续覆盖
            namespace="default",
            source=str(file_path),
            text=text,
            metadata={
                "loader": "text",
                "file_name": file_path.name,
                "file_size": file_path.stat().st_size,
                "encoding": "utf-8",   # TODO: 从 _try_read_text 返回实际编码
            },
        )