"""
2026-07-28 Mini-MCP 服务端与两种教学 transport。

包含：
- `MiniMCPServer`：纯协议 dispatch；
- `MiniMCPHTTPServer`：标准库 HTTP server；
- `run_stdio`：newline-delimited JSON over stdin/stdout。

核心思想：
2026 modern era 的 MCP“协议核心”是 stateless 的：
- 没有 initialize/initialized handshake；
- 没有 Mcp-Session-Id；
- 每个请求自描述；
- 任意请求理论上都能落到任意无状态 server instance。

应用当然仍然可以有状态，只是状态应该显式化，例如把 handle
作为 tool argument 在请求之间传递，而不是藏在 transport session 中。
"""

from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
import json
import sys
from typing import Any, Mapping, TextIO

from .protocol import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    META_CLIENT_CAPABILITIES,
    META_PROTOCOL_VERSION,
    META_SERVER_INFO,
    PROTOCOL_VERSION,
    UNSUPPORTED_PROTOCOL_VERSION,
    CachePolicy,
    JsonRpcError,
    Tool,
    make_error,
    make_success,
    normalize_tool_result,
    parse_json,
    protocol_version_from_request,
    header_value,
    request_meta,
    strip_meta,
    validate_basic_json_schema,
    validate_request,
)


class MiniMCPServer:
    """零第三方依赖、协议级无状态的教学 MCP Server。

    当前只支持：
    - server/discover
    - tools/list
    - tools/call

    故意不支持：
    - resources / prompts；
    - subscriptions/listen；
    - MRTR input_required；
    - auth；
    - 2025 legacy era。
    """

    def __init__(
        self,
        *,
        name: str = "hi-agent-mini-mcp",
        version: str = "0.1.0",
        cache_policy: CachePolicy | None = None,
        page_size: int = 50,
    ) -> None:
        if page_size <= 0:
            raise ValueError(
                "page_size must be positive"
            )

        self.name = name
        self.version = version

        # 生产系统默认更应该保守：ttl=0 / private。
        # 为了教学演示 client cache，这里保留 60 秒 public。
        self.cache_policy = (
            cache_policy
            or CachePolicy(
                ttl_ms=60_000,
                cache_scope="public",
            )
        )

        self.page_size = page_size
        self._tools: dict[str, Tool] = {}

    # ------------------------------------------------------------------
    # Tool registry
    # ------------------------------------------------------------------

    def register_tool(self, tool: Tool) -> None:
        """注册一个工具。

        name 是协议可见标识，因此这里至少做最小合法性约束。
        完整 MCP Name 规范比这里更严格，生产代码应交给官方 SDK。
        """
        if not tool.name or "/" in tool.name:
            raise ValueError(
                "tool name must be non-empty "
                "and must not contain '/'"
            )

        if tool.name in self._tools:
            raise ValueError(
                f"tool already registered: {tool.name}"
            )

        self._tools[tool.name] = tool

    def register(
        self,
        name: str,
        handler,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        """一个便捷注册 API，把普通 Python handler 包成 Tool。"""

        self.register_tool(
            Tool(
                name=name,
                handler=handler,
                description=description,
                input_schema=(
                    input_schema
                    or {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    }
                ),
                output_schema=output_schema,
            )
        )

    def tool_definitions(self) -> list[dict[str, Any]]:
        """返回稳定顺序的 tool catalog。

        2026 cacheable list 的一个重要目标是：
        同样的工具集合应产生 deterministic ordering，
        这样：
        - 客户端 cache 更稳定；
        - 上游 LLM prompt cache 更稳定；
        - 测试更可重复。
        """
        return [
            self._tools[name].definition()
            for name in sorted(self._tools)
        ]

    # ------------------------------------------------------------------
    # Request entry
    # ------------------------------------------------------------------

    def handle(
        self,
        raw_request: str | bytes | Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
        transport: str = "stdio",
    ) -> dict[str, Any]:
        """处理一个“完全自包含”的请求。

        这个函数本身不保存 session，不依赖前一次请求。
        """

        request_id: Any = None

        try:
            request = parse_json(raw_request)
            request_id = request.get("id")

            validate_request(request)
            self._validate_protocol_headers(
                request,
                headers or {},
                transport,
            )
            # For HTTP, check header/body agreement before checking whether
            # the agreed version is supported. Otherwise a version mismatch
            # could be incorrectly reported as UnsupportedProtocolVersion.
            self._validate_modern_envelope(request)

            result = self._dispatch(request)

            # 2026 final spec：server identity 通过 result._meta
            # 标记在每个响应上。这里集中处理，避免每个 handler 重复写。
            result = self._stamp_server_info(result)

            # 2026 wire result 需要 resultType discriminator。
            return make_success(
                request_id,
                result,
            )

        except JsonRpcError as exc:
            return make_error(
                request_id,
                exc,
            )

        except Exception as exc:
            # 教学版把未捕获异常映射为 JSON-RPC internal error。
            # 生产服务通常不会把原始 exception 文本直接返回给远端，
            # 以免泄漏路径、密钥或内部实现。
            return make_error(
                request_id,
                JsonRpcError(
                    INTERNAL_ERROR,
                    "Internal error",
                    str(exc),
                ),
            )

    def _validate_modern_envelope(
        self,
        request: Mapping[str, Any],
    ) -> None:
        """验证 2026 modern-era 请求最关键的 per-request envelope。

        `protocolVersion` 必须存在；
        `clientCapabilities` 也要求是 object。

        `clientInfo` 在 final 2026 spec 中是 SHOULD，不做强制要求。
        """
        meta = request_meta(request)

        if meta.get(META_PROTOCOL_VERSION) != PROTOCOL_VERSION:
            raise JsonRpcError(
                UNSUPPORTED_PROTOCOL_VERSION,
                "Mini-MCP requires protocol revision 2026-07-28",
                {
                    "requested": meta.get(
                        META_PROTOCOL_VERSION
                    ),
                    "supported": [PROTOCOL_VERSION],
                },
            )

        capabilities = meta.get(
            META_CLIENT_CAPABILITIES
        )
        if not isinstance(capabilities, dict):
            raise JsonRpcError(
                INVALID_PARAMS,
                (
                    "params._meta must contain "
                    "io.modelcontextprotocol/clientCapabilities object"
                ),
            )

    def _validate_protocol_headers(
        self,
        request: Mapping[str, Any],
        headers: Mapping[str, str],
        transport: str,
    ) -> None:
        """验证 2026 Streamable HTTP 的路由头。

        stdio 没有 HTTP headers，因此只检查请求 envelope。
        HTTP 时检查：
        - MCP-Protocol-Version
        - Mcp-Method
        - 对 tools/call 检查 Mcp-Name

        头和 body 不一致属于 MCP `HeaderMismatch` (-32020)，
        而不是普通 JSON-RPC Invalid Params。
        """

        if transport != "http":
            return

        version = header_value(
            headers,
            "MCP-Protocol-Version",
        )
        body_version = request_meta(request).get(
            META_PROTOCOL_VERSION
        )

        if not version or version != body_version:
            raise JsonRpcError(
                HEADER_MISMATCH,
                (
                    "MCP-Protocol-Version header "
                    "must be present and match request _meta"
                ),
                {
                    "header": version,
                    "body": body_version,
                },
            )

        method = request["method"]
        routed_method = header_value(
            headers,
            "Mcp-Method",
        )

        if not routed_method or routed_method != method:
            raise JsonRpcError(
                HEADER_MISMATCH,
                (
                    "Mcp-Method must be present "
                    "and match the JSON-RPC method"
                ),
                {
                    "header": routed_method,
                    "body": method,
                },
            )

        if method == "tools/call":
            params = strip_meta(
                request.get("params")
            )
            tool_name = params.get("name")
            routed_name = header_value(
                headers,
                "Mcp-Name",
            )

            if (
                not routed_name
                or routed_name != tool_name
            ):
                raise JsonRpcError(
                    HEADER_MISMATCH,
                    (
                        "Mcp-Name must be present "
                        "and match tools/call params.name"
                    ),
                    {
                        "header": routed_name,
                        "body": tool_name,
                    },
                )

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        """按 JSON-RPC method 路由到具体 MCP handler。"""

        method = request["method"]

        # reserved `_meta` 属于协议层，不应该作为业务参数传入。
        params = strip_meta(
            request.get("params")
        )

        if method == "server/discover":
            return self._discover()

        if method == "tools/list":
            return self._list_tools(params)

        if method == "tools/call":
            return self._call_tool(params)

        raise JsonRpcError(
            METHOD_NOT_FOUND,
            f"Method not found: {method}",
        )

    def _discover(self) -> dict[str, Any]:
        """返回 modern-era discovery document。

        `server/discover` 不是 initialize：
        - 不建立 session；
        - 不改变服务端后续状态；
        - 客户端可以不调用它，直接调用工具。

        server identity 不放在普通 body field，
        而由 `_stamp_server_info()` 放进 result._meta。
        """
        result = {
            "supportedVersions": [
                PROTOCOL_VERSION,
            ],
            "capabilities": {
                "tools": {
                    "listChanged": False,
                }
            },
            "instructions": (
                "Use the tools exposed by "
                "this educational server."
            ),
        }

        return self.cache_policy.apply(result)

    def _list_tools(
        self,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """分页返回工具目录。"""

        cursor = params.get("cursor")
        start = self._decode_cursor(cursor)

        definitions = self.tool_definitions()
        page = definitions[
            start : start + self.page_size
        ]

        result: dict[str, Any] = {
            "tools": page,
        }

        next_start = start + len(page)

        if next_start < len(definitions):
            result["nextCursor"] = (
                self._encode_cursor(next_start)
            )

        return self.cache_policy.apply(result)

    def _call_tool(
        self,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """执行一次工具调用。

        协议层参数错误 -> JSON-RPC error。
        工具执行阶段错误 -> `result.isError=true`。
        """

        name = params.get("name")
        arguments = params.get(
            "arguments",
            {},
        )

        if not isinstance(name, str) or not name:
            raise JsonRpcError(
                INVALID_PARAMS,
                "tools/call requires params.name",
            )

        if not isinstance(arguments, dict):
            raise JsonRpcError(
                INVALID_PARAMS,
                (
                    "tools/call params.arguments "
                    "must be an object"
                ),
            )

        tool = self._tools.get(name)
        if tool is None:
            raise JsonRpcError(
                INVALID_PARAMS,
                f"Unknown tool: {name}",
            )

        try:
            # 入参 contract。
            validate_basic_json_schema(
                arguments,
                tool.input_schema,
            )

            value = tool.handler(arguments)

            # 这个 Mini-MCP 的 handler pipeline 是同步的。
            if inspect.isawaitable(value):
                raise RuntimeError(
                    (
                        "Mini-MCP handlers are synchronous; "
                        "use an async SDK for async tools"
                    )
                )

            result = normalize_tool_result(value)

            # 如果声明了 outputSchema，并且存在 structuredContent，
            # 就验证输出的结构化部分。
            if (
                tool.output_schema is not None
                and "structuredContent" in result
            ):
                validate_basic_json_schema(
                    result["structuredContent"],
                    tool.output_schema,
                )

            return result

        except JsonRpcError as exc:
            # 注意：到这里说明“RPC 已经合法进入 tool 执行阶段”，
            # 因此把 tool-level 参数/业务错误暴露为 isError，
            # 让 Agent 能看到失败并修正调用。
            message = (
                exc.message
                if exc.data is None
                else f"{exc.message}: {exc.data}"
            )
            return (
                normalize_tool_result(message)
                | {"isError": True}
            )

        except Exception as exc:
            return (
                normalize_tool_result(str(exc))
                | {"isError": True}
            )

    def _stamp_server_info(
        self,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """给 2026 result._meta 加 server identity。

        serverInfo 只是自报身份，用于显示 / logging / debugging，
        不能当安全凭据。
        """
        stamped = dict(result)
        meta = dict(stamped.get("_meta") or {})

        meta.setdefault(
            META_SERVER_INFO,
            {
                "name": self.name,
                "version": self.version,
            },
        )

        stamped["_meta"] = meta
        return stamped

    # ------------------------------------------------------------------
    # Cursor
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_cursor(index: int) -> str:
        """把内部数组索引编码成 opaque cursor。"""
        return (
            base64.urlsafe_b64encode(
                str(index).encode("ascii")
            )
            .decode("ascii")
            .rstrip("=")
        )

    @staticmethod
    def _decode_cursor(cursor: Any) -> int:
        """把 opaque cursor 解析回索引。

        客户端只能把 cursor 当 opaque string，
        不应该依赖这里的 base64 实现细节。
        """
        if cursor is None:
            return 0

        if not isinstance(cursor, str):
            raise JsonRpcError(
                INVALID_PARAMS,
                "cursor must be an opaque string",
            )

        try:
            padded = (
                cursor
                + "=" * (-len(cursor) % 4)
            )
            value = int(
                base64.urlsafe_b64decode(
                    padded
                ).decode("ascii")
            )
        except (
            ValueError,
            UnicodeDecodeError,
            base64.binascii.Error,
        ) as exc:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Invalid cursor",
            ) from exc

        if value < 0:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Invalid cursor",
            )

        return value


class MiniMCPHTTPServer:
    """基于 Python 标准库的最小无状态 MCP HTTP Server。"""

    def __init__(
        self,
        mcp_server: MiniMCPServer,
        host: str = "127.0.0.1",
        port: int = 8765,
    ):
        self.mcp_server = mcp_server
        self.host = host
        self.port = port

        self.httpd = ThreadingHTTPServer(
            (host, port),
            self._handler_class(),
        )

    def _handler_class(self):
        """创建绑定当前 MiniMCPServer 的 request handler class。"""

        mcp_server = self.mcp_server

        class Handler(BaseHTTPRequestHandler):
            server_version = "MiniMCP/2026.07.28"

            def do_POST(self) -> None:
                """处理唯一支持的 HTTP RPC endpoint: POST /mcp。"""

                if self.path != "/mcp":
                    self.send_error(
                        404,
                        "Only POST /mcp is supported",
                    )
                    return

                length = int(
                    self.headers.get(
                        "Content-Length",
                        "0",
                    )
                )

                body = self.rfile.read(length)
                headers = {
                    key: value
                    for key, value in self.headers.items()
                }

                response = mcp_server.handle(
                    body,
                    headers=headers,
                    transport="http",
                )

                payload = json.dumps(
                    response,
                    ensure_ascii=False,
                ).encode("utf-8")

                # SEP-2243 路由头 mismatch 属于 HTTP 400 +
                # JSON-RPC -32020。
                error = response.get("error")
                error_code = (
                    error.get("code")
                    if isinstance(error, dict)
                    else None
                )
                status = (
                    400
                    if error_code == HEADER_MISMATCH
                    else 200
                )

                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    "application/json",
                )
                self.send_header(
                    "Content-Length",
                    str(len(payload)),
                )
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                # 2026 modern Mini-MCP 不使用旧版 GET SSE listener。
                self.send_error(
                    405,
                    "GET is not used by stateless Mini-MCP",
                )

            def do_DELETE(self) -> None:
                # 没有协议级 session，所以也没有 DELETE session。
                self.send_error(
                    405,
                    "DELETE is not used by stateless Mini-MCP",
                )

            def log_message(
                self,
                format: str,
                *args: Any,
            ) -> None:
                # 教学测试保持安静。
                return

        return Handler

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def run_stdio(
    server: MiniMCPServer,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    """运行一个最小 stdio transport。

    约定：
    - stdin 每行一个 JSON-RPC request；
    - stdout 每行一个 JSON-RPC response；
    - 不保存 session state。

    真实官方 SDK 的 stdio transport 会处理更多生命周期、
    framing、兼容性和取消语义。
    """
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout

    for line in input_stream:
        if not line.strip():
            continue

        response = server.handle(
            line,
            transport="stdio",
        )

        output_stream.write(
            json.dumps(
                response,
                ensure_ascii=False,
            )
            + "\n"
        )
        output_stream.flush()
