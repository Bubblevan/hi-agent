from .base import BaseLoader
from retrieval.models import Document
from pathlib import Path

class TextLoader(BaseLoader):
    """纯文本加载器。UTF-8 → GB18030 降级。"""

    def load(
        self, path: str | Path, *, user_id: str, namespace: str
    ) -> Document:
        file_path = self._resolve(path)
        text, encoding = self._try_read_text_with_encoding(file_path)

        return Document.build(
            user_id=user_id,
            namespace=namespace,
            source=str(file_path),
            text=text,
            metadata={
                "loader": "text",
                "file_name": file_path.name,
                "file_size": file_path.stat().st_size,
                "encoding": encoding,
            },
        )
