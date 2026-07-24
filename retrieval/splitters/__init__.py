# splitters/__init__.py

# 作为工厂入口，让 pipeline 完全不依赖具体 splitter 类名
from models import Document
from splitters.base import TextSplitter
from splitters.recursive import RecursiveSplitter
from splitters.markdown import MarkdownSplitter

def get_splitter(document: Document) -> TextSplitter:
    """根据文档元数据选择合适的分块器"""
    loader = document.metadata.get("loader", "")
    if loader in ("markdown", "markitdown"):
        return MarkdownSplitter()
    return RecursiveSplitter()

# 这样 pipeline 中只需要：
# ```python
# from splitters import get_splitter
# splitter = get_splitter(doc)
# chunks = splitter.split(doc)
# ```
# 而无需知道具体用了 RecursiveSplitter 还是 MarkdownSplitter