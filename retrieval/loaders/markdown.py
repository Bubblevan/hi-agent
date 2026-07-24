import yaml
from retrieval.models import Document
from pathlib import Path
from .base import BaseLoader
from typing import Any

class MarkdownLoader(BaseLoader):
    """
    Markdown 加载器。解析 YAML frontmatter，保留正文 Markdown。

    输入：.md 文件
    处理：
      1. UTF-8 读取全文
      2. 检测 --- ... --- frontmatter 块
      3. YAML 解析 → 提取 title / date / tags 等已知字段
      4. 正文保持原始 Markdown 不转换
    输出：Document
      - text = 正文 Markdown（不含 frontmatter）
      - metadata = {title, date, tags, ...} + 所有 frontmatter 字段
    失败：同 BaseLoader._resolve
    """

    def load(self, path: str | Path) -> Document:
        file_path = self._resolve(path)
        raw = file_path.read_text(encoding="utf-8")

        frontmatter: dict[str, Any] = {}
        body = raw

        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    pass  # frontmatter 解析失败 → 全文当正文
                body = parts[2].strip()

        return Document.build(
            user_id="default",
            namespace="default",
            source=str(file_path),
            text=body,
            metadata={
                "loader": "markdown",
                "file_name": file_path.name,
                "title": frontmatter.get("title", file_path.stem),
                "date": frontmatter.get("date"),
                "tags": frontmatter.get("tags", []),
                "topics": frontmatter.get("topics", []),
                "projects": frontmatter.get("projects", []),
                "summary": frontmatter.get("summary"),
                # 原始 frontmatter 全量保留，不丢字段
                "raw_frontmatter": frontmatter,
            },
        )