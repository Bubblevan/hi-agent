"""Convert one catalog entry into Hi-Agent's existing MyTool abstraction."""

from __future__ import annotations

import json
from typing import Any

from tools.base import MyTool, ToolParameter

from .catalog import MCPToolEntry
from .manager import MCPCallResult, MCPManager


class MCPToolAdapter(MyTool):
    """A protocol boundary that looks like a normal Hi-Agent tool."""

    def __init__(self, manager: MCPManager, entry: MCPToolEntry) -> None:
        super().__init__(entry.canonical_tool_name, entry.description)
        self.manager = manager
        self.entry = entry

    def get_parameters(self) -> list[ToolParameter]:
        properties = self.entry.input_schema.get("properties", {})
        required = set(self.entry.input_schema.get("required", []))
        return [
            ToolParameter(
                name=name,
                type=str(schema.get("type", "any")),
                description=str(schema.get("description", "")),
                required=name in required,
                default=schema.get("default"),
            )
            for name, schema in properties.items()
        ]

    def call_result(self, parameters: dict[str, Any]) -> MCPCallResult:
        return self.manager.call_tool(
            self.entry.original_tool_name,
            parameters,
        )

    @staticmethod
    def render_result(result: MCPCallResult) -> str:
        """Render one already completed SDK result without calling the tool."""

        if result.structured_content is not None:
            rendered = json.dumps(
                result.structured_content,
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            rendered = "\n".join(
                str(item.get("text", item))
                if isinstance(item, dict)
                else str(item)
                for item in result.content
            )
        if result.is_error:
            return f"MCP tool error: {rendered}"
        return rendered

    def run(self, parameters: dict[str, Any]) -> str:
        return self.render_result(self.call_result(parameters))
