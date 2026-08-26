"""A deterministic, SDK-neutral catalog of discovered MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .manager import MCPManager


@dataclass(frozen=True, slots=True)
class MCPToolEntry:
    server_id: str
    server_name: str
    server_version: str
    original_tool_name: str
    canonical_tool_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None
    ttl_ms: int
    cache_scope: str
    risk: str = "read_only"
    tags: tuple[str, ...] = ()
    discovered_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def estimated_schema_tokens(self) -> int:
        return max(
            1,
            (
                len(self.canonical_tool_name)
                + len(self.description)
                + len(str(self.input_schema))
                + len(str(self.output_schema or {}))
            )
            // 4,
        )


class MCPToolCatalog:
    """Stores tools from one or more Managers with stable naming."""

    def __init__(self) -> None:
        self._entries: dict[str, MCPToolEntry] = {}

    def entries(self) -> list[MCPToolEntry]:
        return [self._entries[name] for name in sorted(self._entries)]

    def get(self, canonical_name: str) -> MCPToolEntry:
        try:
            return self._entries[canonical_name]
        except KeyError as exc:
            raise KeyError(f"unknown MCP tool: {canonical_name}") from exc

    def remove_server(self, server_id: str) -> None:
        self._entries = {
            name: entry
            for name, entry in self._entries.items()
            if entry.server_id != server_id
        }

    def refresh(self, manager: MCPManager) -> list[MCPToolEntry]:
        """Replace one Server's entries from its current tools/list result."""

        discovered = manager.list_tools()
        server_info = discovered.get("serverInfo") or {}
        server_name = (
            server_info.get("name")
            or manager.config.display_name
            or manager.config.server_id
        )
        server_version = str(server_info.get("version", ""))
        now = datetime.now(timezone.utc).isoformat()
        new_entries: dict[str, MCPToolEntry] = {}

        for tool in discovered.get("tools", []):
            original_name = str(tool["name"])
            canonical_name = f"{manager.config.server_id}.{original_name}"
            annotations = tool.get("annotations") or {}
            risk = self._infer_risk(original_name, annotations)
            new_entries[canonical_name] = MCPToolEntry(
                server_id=manager.config.server_id,
                server_name=server_name,
                server_version=server_version,
                original_tool_name=original_name,
                canonical_tool_name=canonical_name,
                description=str(tool.get("description") or ""),
                input_schema=tool.get("inputSchema") or {},
                output_schema=tool.get("outputSchema"),
                ttl_ms=int(discovered.get("ttlMs", 0) or 0),
                cache_scope=str(discovered.get("cacheScope", "private")),
                risk=risk,
                tags=tuple(tool.get("tags") or ()),
                discovered_at=now,
                metadata={"raw_definition": tool},
            )

        self.remove_server(manager.config.server_id)
        self._entries.update(new_entries)
        return list(new_entries.values())

    @staticmethod
    def _infer_risk(name: str, annotations: dict[str, Any]) -> str:
        """Conservative fallback when a server omits tool annotations.

        Tool annotations are hints, not authorization.  A Host still needs a
        local policy.  For this teaching Host, obvious mutating verbs are
        classified conservatively so a missing annotation cannot accidentally
        turn delete/write operations into read-only calls.
        """

        lowered = name.lower()
        if annotations.get("destructiveHint") or any(
            word in lowered
            for word in ("delete", "remove", "drop", "destroy", "shell", "exec")
        ):
            return "dangerous"
        if annotations.get("idempotentHint") is False or any(
            word in lowered
            for word in ("write", "create", "update", "commit", "push", "move")
        ):
            return "write"
        return "read_only"

    def register(self, entry: MCPToolEntry) -> None:
        if entry.canonical_tool_name in self._entries:
            raise ValueError(
                f"canonical tool already registered: {entry.canonical_tool_name}"
            )
        self._entries[entry.canonical_tool_name] = entry

    def __len__(self) -> int:
        return len(self._entries)
