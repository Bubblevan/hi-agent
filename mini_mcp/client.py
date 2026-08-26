"""
Mini-MCP 客户端。

包含两个教学客户端：

1. `MiniMCPClient`
   - 直接调用 Python server 对象；
   - 适合 deterministic unit test；
   - 不经过真实 socket。

2. `MiniMCPHTTPClient`
   - 只使用 Python 标准库；
   - 真实 POST `/mcp`；
   - 用来观察 2026 Streamable HTTP 的 headers / body。

两者都只实现：
- server/discover
- tools/list
- tools/call

它们不是完整 MCP Host，也没有模型 tool selection。
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .protocol import (
    INVALID_PARAMS,
    PROTOCOL_VERSION,
    JsonRpcError,
    make_request,
)


@dataclass
class _CacheEntry:
    """客户端本地 cache entry。

    `result`
        服务端返回并已合并分页后的工具目录。
    `received_at`
        使用 monotonic clock 记录收到时间，
        避免系统墙上时钟调整影响 TTL 判断。
    """

    result: dict[str, Any]
    received_at: float


class MiniMCPClient:
    """进程内教学客户端。

    它不是真正的 stdio transport：
    `server.handle(...)` 是直接 Python 函数调用。

    这样设计的价值在于：
    - 单测快；
    - 不依赖 subprocess；
    - 可以稳定验证协议 envelope / dispatch / cache 行为。

    真正的 stdio 演示由 `run_stdio()` + 子进程完成更合适。
    """

    _counter = 0

    def __init__(
        self,
        server,
        *,
        client_name: str = "hi-agent-mini-client",
        client_version: str = "0.1.0",
        transport: str = "stdio",
        client_capabilities: Mapping[str, Any] | None = None,
        clock=time.monotonic,
    ) -> None:
        if transport not in {"stdio", "http"}:
            raise ValueError(
                "transport must be 'stdio' or 'http'"
            )

        self.server = server
        self.client_name = client_name
        self.client_version = client_version

        # 这是“模拟 transport 类型”，主要决定 HTTP headers 是否需要生成。
        self.transport = transport

        # 2026 modern era 客户端能力是 per-request envelope 的一部分。
        self.client_capabilities = dict(
            client_capabilities or {}
        )

        self.clock = clock
        self._tools_cache: _CacheEntry | None = None

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送一个完整、自描述的 MCP 请求。"""

        request = make_request(
            self._next_id(),
            method,
            params,
            client_info={
                "name": self.client_name,
                "version": self.client_version,
            },
            client_capabilities=self.client_capabilities,
        )

        headers: dict[str, str] = {}

        if self.transport == "http":
            # 2026 Streamable HTTP modern request：
            # protocol version 和 RPC method 都可以让 gateway
            # 在不解析 JSON body 的情况下进行路由 / ACL / 计量。
            headers["MCP-Protocol-Version"] = PROTOCOL_VERSION
            headers["Mcp-Method"] = method

            # `Mcp-Name` 只对具有“subject name / uri”的 RPC 有意义。
            # Mini-MCP 当前只实现 tools/call 的 name mirror。
            if method == "tools/call":
                headers["Mcp-Name"] = str(
                    (params or {}).get("name", "")
                )

        return self.server.handle(
            request,
            headers=headers,
            transport=self.transport,
        )

    def discover(self) -> dict[str, Any]:
        """调用 2026 的可选 `server/discover`。

        2026 不再强制 initialize 握手。
        discovery 只是“如果客户端想提前知道服务器能力，就主动问一次”。
        """
        return self._unwrap(
            self.request("server/discover")
        )

    def list_tools(
        self,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """获取完整工具目录，并演示 2026 cache hints。

        关键点：
        - 服务端 list 本身可以分页；
        - 客户端把所有页合并；
        - TTL 未过期时可以不再请求服务器。

        真实 SDK 还会更谨慎地处理 cache partition / server identity。
        """

        now = self.clock()

        if (
            not force_refresh
            and self._tools_cache is not None
        ):
            ttl_ms = int(
                self._tools_cache.result.get(
                    "ttlMs",
                    0,
                )
            )
            if (
                ttl_ms > 0
                and now
                < self._tools_cache.received_at
                + ttl_ms / 1000
            ):
                return self._tools_cache.result

        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        first_page: dict[str, Any] | None = None

        while True:
            params = (
                {}
                if cursor is None
                else {"cursor": cursor}
            )

            page = self._unwrap(
                self.request(
                    "tools/list",
                    params,
                )
            )

            if first_page is None:
                first_page = page

            tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor")

            if not cursor:
                # cache hints 是整个 list 结果的语义。
                # 为避免错误地只采用“最后一页”的提示，
                # 这里优先保留第一页的 policy。
                policy_page = first_page or page

                merged = {
                    "tools": tools,
                    "ttlMs": policy_page.get(
                        "ttlMs",
                        0,
                    ),
                    "cacheScope": policy_page.get(
                        "cacheScope",
                        "private",
                    ),
                }

                self._tools_cache = _CacheEntry(
                    merged,
                    now,
                )
                return merged

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用一个已经知道名字的工具。"""

        return self._unwrap(
            self.request(
                "tools/call",
                {
                    "name": name,
                    "arguments": dict(arguments or {}),
                },
            )
        )

    def _unwrap(
        self,
        response: Mapping[str, Any],
    ) -> dict[str, Any]:
        """把 wire-level JSON-RPC response 变成高层结果。

        2026 的 `resultType` 是 wire discriminator：
        - complete: 普通完成；
        - input_required: MRTR 需要客户端补输入。

        官方 SDK 会在 wire seam 消费它，不把 `complete`
        暴露给普通应用代码。

        Mini-MCP 暂不实现 MRTR，所以：
        - 只接受 `complete`；
        - 收到其他 resultType 就显式失败；
        - 返回前移除 resultType。
        """

        if "error" in response:
            error = response["error"]
            raise JsonRpcError(
                int(
                    error.get(
                        "code",
                        INVALID_PARAMS,
                    )
                ),
                str(
                    error.get(
                        "message",
                        "MCP request failed",
                    )
                ),
                error.get("data"),
            )

        result = response.get("result")
        if not isinstance(result, dict):
            raise JsonRpcError(
                INVALID_PARAMS,
                "MCP response result must be an object",
            )

        result_type = result.get("resultType")
        if result_type != "complete":
            raise JsonRpcError(
                INVALID_PARAMS,
                (
                    "Mini-MCP only supports "
                    f"resultType='complete', got {result_type!r}"
                ),
            )

        clean = dict(result)
        clean.pop("resultType", None)
        return clean

    @classmethod
    def _next_id(cls) -> int:
        """生成简单的单调递增 JSON-RPC id。"""
        cls._counter += 1
        return cls._counter


class MiniMCPHTTPClient:
    """只依赖 Python 标准库的无状态 HTTP 教学客户端。"""

    def __init__(
        self,
        url: str,
        *,
        client_name: str = "hi-agent-mini-http-client",
        client_version: str = "0.1.0",
        client_capabilities: Mapping[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.client_name = client_name
        self.client_version = client_version
        self.client_capabilities = dict(
            client_capabilities or {}
        )
        self.timeout = timeout
        self._counter = 0

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """通过真实 HTTP POST 发送一个 modern MCP request。"""

        self._counter += 1

        body = make_request(
            self._counter,
            method,
            params,
            client_info={
                "name": self.client_name,
                "version": self.client_version,
            },
            client_capabilities=self.client_capabilities,
        )

        headers = {
            "Content-Type": "application/json",
            # MCP body 中虽然也有 protocolVersion，
            # 2026 Streamable HTTP 仍要求这个 header。
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            "Mcp-Method": method,
        }

        if method == "tools/call":
            headers["Mcp-Name"] = str(
                (params or {}).get("name", "")
            )

        request = Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout,
            ) as response:
                return json.loads(
                    response.read().decode("utf-8")
                )
        except HTTPError as exc:
            # 2026 HTTP 层的一部分协议错误会用 HTTP 400
            # 同时 body 仍是可解析的 JSON-RPC error。
            # urllib 默认会把 400 直接抛异常，所以这里把 body
            # 重新读回来，交给 `_unwrap()` 按协议错误处理。
            body_bytes = exc.read()
            try:
                return json.loads(
                    body_bytes.decode("utf-8")
                )
            except Exception:
                raise

    def discover(self) -> dict[str, Any]:
        return MiniMCPClient._unwrap(
            self,
            self.request("server/discover"),
        )

    def list_tools(self) -> dict[str, Any]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        first_page: dict[str, Any] | None = None

        while True:
            params = (
                {}
                if cursor is None
                else {"cursor": cursor}
            )

            page = MiniMCPClient._unwrap(
                self,
                self.request(
                    "tools/list",
                    params,
                ),
            )

            if first_page is None:
                first_page = page

            tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor")

            if not cursor:
                policy_page = first_page or page
                return {
                    "tools": tools,
                    "ttlMs": policy_page.get(
                        "ttlMs",
                        0,
                    ),
                    "cacheScope": policy_page.get(
                        "cacheScope",
                        "private",
                    ),
                }

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return MiniMCPClient._unwrap(
            self,
            self.request(
                "tools/call",
                {
                    "name": name,
                    "arguments": dict(arguments or {}),
                },
            ),
        )