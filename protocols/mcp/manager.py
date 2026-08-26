"""MCP Host manager built on the official Python SDK.

This module deliberately does not implement JSON-RPC or MCP framing.  The
official SDK owns those responsibilities.  The manager converts SDK models
into small, stable Hi-Agent-facing dictionaries so the rest of the runtime
does not depend on SDK model names.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import inspect
from typing import Any

from mcp import Client, Implementation


def _dump(value: Any) -> Any:
    """Convert an SDK model to JSON-shaped data without leaking model types."""

    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, exclude_none=False)
    if isinstance(value, list):
        return [_dump(item) for item in value]
    if isinstance(value, dict):
        return {key: _dump(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    """A named MCP endpoint.

    source can be an official SDK Server/MCPServer object, a URL, a transport,
    or StdioServerParameters.  Keeping this type opaque lets tests use an
    in-process server while production can use stdio or Streamable HTTP.
    """

    server_id: str
    source: Any
    display_name: str | None = None
    client_name: str = "hi-agent-mcp-host"
    client_version: str = "0.1.0"


@dataclass(frozen=True, slots=True)
class MCPCallResult:
    """SDK-neutral result returned by one tools/call."""

    content: list[Any]
    structured_content: Any = None
    is_error: bool = False
    result_type: str = "complete"
    raw: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "content": self.content,
            "structuredContent": self.structured_content,
            "isError": self.is_error,
            "resultType": self.result_type,
        }
        if self.raw is not None:
            result["raw"] = self.raw
        return result


class MCPManager:
    """Lifecycle and invocation boundary for one MCP Server.

    The async methods are the preferred runtime API.  The sync methods are a
    deliberate bridge for Hi-Agent's existing synchronous MyTool interface.
    A sync call must happen outside an already-running event loop.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        if not config.server_id.strip():
            raise ValueError("server_id must not be blank")
        self.config = config
        self._last_server_info: dict[str, Any] | None = None
        self._last_protocol_version: str | None = None

    @property
    def server_info(self) -> dict[str, Any] | None:
        return self._last_server_info

    @property
    def protocol_version(self) -> str | None:
        return self._last_protocol_version

    async def _with_client(self, operation):
        client = Client(
            self.config.source,
            client_info=Implementation(
                name=self.config.client_name,
                version=self.config.client_version,
            ),
        )
        async with client:
            self._last_protocol_version = client.protocol_version
            self._last_server_info = _dump(client.server_info)
            if inspect.iscoroutinefunction(operation):
                return await operation(client)
            return operation(client)

    async def async_discover(self) -> dict[str, Any]:
        """Enter the SDK client and return the negotiated/discovered view."""

        async def discover(client: Client) -> dict[str, Any]:
            return {
                "serverInfo": _dump(client.server_info),
                "protocolVersion": client.protocol_version,
                "capabilities": _dump(client.server_capabilities),
                "instructions": client.instructions,
            }

        return await self._with_client(discover)

    async def async_list_tools(self) -> dict[str, Any]:
        async def list_tools(client: Client) -> dict[str, Any]:
            tools: list[dict[str, Any]] = []
            cursor: str | None = None
            first_payload: dict[str, Any] | None = None
            while True:
                page = await client.list_tools(cursor=cursor)
                payload = _dump(page)
                if first_payload is None:
                    first_payload = payload
                tools.extend(payload.get("tools", []))
                cursor = payload.get("nextCursor")
                if not cursor:
                    break
            first_payload = first_payload or {}
            return {
                "tools": tools,
                "nextCursor": None,
                "ttlMs": first_payload.get("ttlMs", 0),
                "cacheScope": first_payload.get("cacheScope", "private"),
                "serverInfo": _dump(client.server_info),
            }

        return await self._with_client(list_tools)

    async def async_call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPCallResult:
        async def call(client: Client) -> MCPCallResult:
            result = await client.call_tool(name, arguments or {})
            payload = _dump(result)
            return MCPCallResult(
                content=payload.get("content", []),
                structured_content=payload.get("structuredContent"),
                is_error=bool(payload.get("isError", False)),
                result_type=payload.get("resultType", "complete"),
                raw=payload,
            )

        return await self._with_client(call)

    @staticmethod
    def _run(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "MCPManager sync methods cannot run inside an active event loop; "
            "use the async_* method instead"
        )

    def discover(self) -> dict[str, Any]:
        return self._run(self.async_discover())

    def list_tools(self) -> dict[str, Any]:
        return self._run(self.async_list_tools())

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> MCPCallResult:
        return self._run(self.async_call_tool(name, arguments))
