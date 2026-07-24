from abc import ABC, abstractmethod
from pathlib import Path
from retrieval.models import Document

class BaseLoader(ABC):
    """所有 loader 的抽象基类。一个文件 → 一个 Document。"""

    @abstractmethod
    def load(self, path: str | Path) -> Document:
        """
        加载单个文件为 Document。

        必须抛出的异常：
          FileNotFoundError  — 路径不存在
          ValueError         — 文件为空
          UnicodeDecodeError — 所有编码尝试均失败
        """
        ...

    # ---------- 共享工具 ----------

    @staticmethod
    def _resolve(path: str | Path) -> Path:
        """校验路径存在且非空，返回 resolved Path。所有子类在 load() 第一行调用。"""
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"文件不存在: {p}")
        if p.stat().st_size == 0:
            raise ValueError(f"文件为空: {p}")
        return p

    @staticmethod
    def _try_read_text(file_path: Path) -> str:
        """先 UTF-8，失败再 gbk。都不行就抛 UnicodeDecodeError。"""
        for encoding in ("utf-8", "gbk"):
            try:
                return file_path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError(
            "utf-8/gbk",
            b"",
            0, 1,
            f"无法以 UTF-8 或 GBK 解码: {file_path}"
        )
    