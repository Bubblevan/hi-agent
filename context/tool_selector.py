"""MCP-aware tool selection built on Hi-Agent's existing Context selector."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from context.models import ContextBudget, ContextItem
from context.selector import select_items
from protocols.mcp.host.catalog import MCPToolEntry


def _terms(text: str) -> set[str]:
    terms = {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9_]+", text)
        if token.strip()
    }
    # A tiny bilingual bridge keeps the lab deterministic for Chinese task
    # text while leaving real retrieval/ranking replaceable later.
    aliases = {
        "搜索": "search",
        "查找": "search",
        "项目": "project",
        "代码": "code",
        "文件": "file",
        "读取": "read",
        "协议": "protocol",
        "总结": "summary",
    }
    terms.update(value for key, value in aliases.items() if key in text)
    expanded: set[str] = set(terms)
    for token in list(terms):
        expanded.update(part for part in token.split("_") if part)
    return expanded


@dataclass(frozen=True, slots=True)
class ToolSelection:
    selected: list[MCPToolEntry]
    dropped: list[MCPToolEntry]
    reasons: dict[str, str]
    total_tokens: int


class MCPToolSelector:
    """Retrieve relevant catalog entries, then apply the existing token budget."""

    def select(
        self,
        query: str,
        entries: Iterable[MCPToolEntry],
        *,
        budget: ContextBudget | None = None,
    ) -> ToolSelection:
        entries = list(entries)
        query_terms = _terms(query)
        scored: list[tuple[int, int, MCPToolEntry]] = []
        reasons: dict[str, str] = {}

        for index, entry in enumerate(entries):
            searchable = _terms(
                " ".join(
                    [
                        entry.canonical_tool_name,
                        entry.original_tool_name,
                        entry.description,
                        " ".join(entry.tags),
                    ]
                )
            )
            score = len(query_terms & searchable)
            if score > 0:
                scored.append((score, index, entry))
                reasons[entry.canonical_tool_name] = (
                    f"lexical overlap score={score}"
                )
            else:
                reasons[entry.canonical_tool_name] = "no query overlap"

        scored.sort(key=lambda item: (-item[0], item[1]))
        candidates = [entry for _, _, entry in scored]
        if budget is None:
            budget = ContextBudget(
                soft_limit=1200,
                hard_limit=1600,
                output_reserve=200,
            )

        context_items = [
            ContextItem(
                item_id=entry.canonical_tool_name,
                kind="mcp_tool_schema",
                content=(
                    f"{entry.canonical_tool_name}: "
                    f"{entry.description or 'MCP tool'}"
                ),
                source=f"mcp:{entry.server_id}",
                priority=max(1, score),
                required=False,
                token_count=entry.estimated_schema_tokens,
                metadata={"entry": entry},
            )
            for score, _, entry in scored
        ]
        selected_items = select_items(context_items, budget)
        selected_ids = {item.item_id for item in selected_items}
        selected = [
            entry for entry in candidates
            if entry.canonical_tool_name in selected_ids
        ]
        dropped = [
            entry for entry in entries
            if entry.canonical_tool_name not in selected_ids
        ]
        for entry in dropped:
            if entry.canonical_tool_name in reasons and reasons[entry.canonical_tool_name] != "no query overlap":
                reasons[entry.canonical_tool_name] += "; budget or lower priority"
        return ToolSelection(
            selected=selected,
            dropped=dropped,
            reasons=reasons,
            total_tokens=sum(entry.estimated_schema_tokens for entry in selected),
        )
