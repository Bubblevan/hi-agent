"""
2026-08-26 Mini-MCP 的“线协议层”原语。

这一层只关心“线上传输的 JSON 长什么样”，不关心 HTTP Server、
stdin/stdout、Agent Harness 等更上层概念。

教学目标：
- 看懂 JSON-RPC 2.0 的 envelope；
- 看懂 2026 MCP 每个请求上的 `_meta`；
- 看懂 Tool definition / Tool result；
- 看懂 2026 新增的 `resultType` 与 cache hints；
- 通过一个很小的 JSON Schema 子集理解“schema 是协议契约”。

注意：真实 2026-07-28 MCP 支持完整 JSON Schema 2020-12。
这里为了零依赖，只实现教学所需的很小子集。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Callable, Mapping

# ---------------------------------------------------------------------------
# 1. 协议常量
# ---------------------------------------------------------------------------

# MCP 的 RPC 消息仍然建立在 JSON-RPC 2.0 上。
JSONRPC_VERSION = "2.0"

# 这里明确“钉死”教学实现对应的 MCP 规范修订版。
PROTOCOL_VERSION = "2026-07-28"

# 2026 modern era 不再把这些信息只放在 initialize 握手中，
# 而是把协议版本 / 客户端信息 / 客户端能力放进“每个请求”的 params._meta。
META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"

# 2026 final spec 把 server identity 放进“每个响应”的 result._meta。
META_SERVER_INFO = "io.modelcontextprotocol/serverInfo"

# JSON-RPC 标准错误码。
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# MCP 2026 新增的协议级错误码。
# -32020: HTTP 路由头 / body 不一致。
HEADER_MISMATCH = -32020
# -32021: MRTR 场景下服务端要求某项 client capability，而客户端未声明。
MISSING_REQUIRED_CLIENT_CAPABILITY = -32021
# -32022: 请求声明的 MCP 协议版本不被服务端支持。
UNSUPPORTED_PROTOCOL_VERSION = -32022

# Sentinel distinguishes "structuredContent was omitted" from a JSON null
# returned intentionally by a tool.
_NO_STRUCTURED_CONTENT = object()


# ---------------------------------------------------------------------------
# 2. JSON-RPC 错误对象
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JsonRpcError(Exception):
    """可直接序列化到 JSON-RPC `error` 字段的异常。

    `code`:
        JSON-RPC / MCP 错误码。
    `message`:
        面向开发者的简短错误描述。
    `data`:
        可选的结构化上下文，例如 supported versions。
    """

    code: int
    message: str
    data: Any = None

    def to_object(self) -> dict[str, Any]:
        """转换成 JSON-RPC 规定的 error object。"""
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            error["data"] = self.data
        return error


# ---------------------------------------------------------------------------
# 3. 2026 cache hints
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CachePolicy:
    """MCP 2026 cacheable 结果的缓存提示。

    2026-07-28 中，`tools/list`、`prompts/list`、`resources/list`、
    `resources/read` 等可缓存结果会携带：

    - ttlMs: 新鲜期，单位毫秒；0 表示不要缓存；
    - cacheScope:
        - private: 只允许当前调用方私有缓存；
        - public: 可被共享缓存复用。

    Mini-MCP 同时也把它用于 `server/discover`，
    便于教学客户端缓存 discovery 信息。
    """

    ttl_ms: int = 0
    cache_scope: str = "private"

    def __post_init__(self) -> None:
        if self.ttl_ms < 0:
            raise ValueError("ttl_ms must be non-negative")
        if self.cache_scope not in {"public", "private"}:
            raise ValueError("cache_scope must be 'public' or 'private'")

    def apply(self, result: dict[str, Any]) -> dict[str, Any]:
        """把缓存提示写入一个结果对象。"""
        result["ttlMs"] = self.ttl_ms
        result["cacheScope"] = self.cache_scope
        return result


# ---------------------------------------------------------------------------
# 4. Tool 调用结果
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolResult:
    """一个教学版 MCP Tool result。

    `content`
        传统 MCP 内容块列表，例如：
        [{"type": "text", "text": "..."}]

    `structured_content`
        2026 规范允许 `structuredContent` 为任意 JSON value，
        不再局限于 object，因此这里使用 `Any`。

    `is_error`
        这里要区分“两层错误”：

        1. JSON-RPC / 协议错误：
           method 不存在、参数 envelope 非法、协议版本不支持……
           -> 走 JSON-RPC `error`

        2. Tool 自己执行失败：
           比如 read_file 找不到文件、业务校验失败……
           -> 仍然是 JSON-RPC `result`，但 `isError=true`
              这样模型能“看到工具失败”并尝试自我修正。
    """

    content: list[dict[str, Any]]
    structured_content: Any = _NO_STRUCTURED_CONTENT
    is_error: bool = False

    def to_object(self) -> dict[str, Any]:
        result: dict[str, Any] = {"content": self.content}
        if self.structured_content is not _NO_STRUCTURED_CONTENT:
            result["structuredContent"] = self.structured_content
        if self.is_error:
            result["isError"] = True
        return result


# ---------------------------------------------------------------------------
# 5. Tool definition
# ---------------------------------------------------------------------------

@dataclass
class Tool:
    """一个可被 `tools/list` 暴露、被 `tools/call` 调用的工具定义。"""

    name: str
    handler: Callable[[dict[str, Any]], Any]
    description: str = ""

    # 生产 MCP 使用完整 JSON Schema 2020-12。
    # Mini-MCP 为了教学保留 JSON Schema 的原始 dict 形态。
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
        }
    )

    # 2026 允许输出 schema 描述 structuredContent。
    output_schema: dict[str, Any] | None = None

    def definition(self) -> dict[str, Any]:
        """生成 `tools/list` 中暴露给客户端的 Tool 描述。"""
        definition: dict[str, Any] = {
            "name": self.name,
            "inputSchema": self.input_schema,
        }
        if self.description:
            definition["description"] = self.description
        if self.output_schema is not None:
            definition["outputSchema"] = self.output_schema
        return definition


# ---------------------------------------------------------------------------
# 6. JSON-RPC request / response builders
# ---------------------------------------------------------------------------

def make_request(
    request_id: int | str,
    method: str,
    params: Mapping[str, Any] | None = None,
    *,
    client_info: Mapping[str, Any] | None = None,
    client_capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一个 2026 modern-era 自描述请求。

    2025 及更早版本：
        initialize 一次，把 protocolVersion / clientInfo / capabilities
        保存在 session 上。

    2026-07-28：
        initialize 和协议级 session 被移除；
        每个请求都必须能够“独立解释自己”。

    因此这里至少总是放：
        io.modelcontextprotocol/protocolVersion
        io.modelcontextprotocol/clientCapabilities

    `clientInfo` 在 2026 final spec 中从 MUST 降为 SHOULD，
    但我们的教学客户端仍默认每次都发送它。
    """

    request_params = dict(params or {})
    meta = dict(request_params.get("_meta") or {})

    # 协议版本是 modern-era 请求的核心。
    meta[META_PROTOCOL_VERSION] = PROTOCOL_VERSION

    # clientCapabilities 是 2026 per-request envelope 的重要组成部分。
    # 即使当前 Mini-MCP 没实现 elicitation / sampling，也显式发送 {}，
    # 让数据包更贴近真实 2026 wire shape。
    meta[META_CLIENT_CAPABILITIES] = dict(client_capabilities or {})

    if client_info is not None:
        meta[META_CLIENT_INFO] = dict(client_info)

    request_params["_meta"] = meta

    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def make_success(
    request_id: int | str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """构造 2026 modern-era 成功响应。

    2026 wire 层引入 `resultType` discriminator。
    普通完成结果应为 `resultType="complete"`；
    MRTR 会使用 `resultType="input_required"`。

    Mini-MCP 暂时不实现 MRTR，因此默认补 `complete`。
    """
    result_object = dict(result)
    result_object.setdefault("resultType", "complete")
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "result": result_object,
    }


def make_error(
    request_id: int | str | None,
    error: JsonRpcError | Mapping[str, Any],
) -> dict[str, Any]:
    """构造 JSON-RPC error response。"""
    error_object = (
        error.to_object()
        if isinstance(error, JsonRpcError)
        else dict(error)
    )
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": error_object,
    }


# ---------------------------------------------------------------------------
# 7. JSON / JSON-RPC 基础校验
# ---------------------------------------------------------------------------

def parse_json(
    value: str | bytes | Mapping[str, Any],
) -> dict[str, Any]:
    """把字符串 / bytes / Mapping 统一解析为 JSON object。"""
    if isinstance(value, Mapping):
        return dict(value)

    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise JsonRpcError(
            PARSE_ERROR,
            "Invalid JSON",
            str(exc),
        ) from exc

    if not isinstance(parsed, dict):
        raise JsonRpcError(
            INVALID_REQUEST,
            "JSON-RPC request must be an object",
        )
    return parsed


def validate_request(request: Mapping[str, Any]) -> None:
    """验证 Mini-MCP 支持的 JSON-RPC request 基本形态。

    教学实现故意不实现 notification，所以要求必须有 id。
    真实 MCP 仍存在部分 notification / subscription 语义，
    不应把这个限制误认为完整 MCP 规范本身。
    """
    if request.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRpcError(
            INVALID_REQUEST,
            "jsonrpc must be '2.0'",
        )

    if "id" not in request:
        raise JsonRpcError(
            INVALID_REQUEST,
            "Mini-MCP does not implement notifications",
        )

    if not isinstance(request.get("method"), str) or not request["method"]:
        raise JsonRpcError(
            INVALID_REQUEST,
            "method must be a non-empty string",
        )

    params = request.get("params")
    if params is not None and not isinstance(params, dict):
        raise JsonRpcError(
            INVALID_PARAMS,
            "params must be an object",
        )


# ---------------------------------------------------------------------------
# 8. 2026 per-request meta envelope
# ---------------------------------------------------------------------------

def request_meta(request: Mapping[str, Any]) -> dict[str, Any]:
    """读取 params._meta；没有则返回空 dict。"""
    params = request.get("params")
    if not isinstance(params, dict):
        return {}

    meta = params.get("_meta")
    return dict(meta) if isinstance(meta, dict) else {}


def protocol_version_from_request(
    request: Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
) -> str | None:
    """读取请求声明的 MCP protocol version。

    HTTP 场景中同时存在：
    - `MCP-Protocol-Version` header
    - params._meta["io.modelcontextprotocol/protocolVersion"]

    更严格的“一致性检查”由 server 的 header validation 完成。
    """
    if headers:
        header_version = header_value(
            headers,
            "MCP-Protocol-Version",
        )
        if header_version:
            return header_version

    meta = request_meta(request)
    value = meta.get(META_PROTOCOL_VERSION)
    return value if isinstance(value, str) else None


def strip_meta(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """移除协议层 `_meta`，避免 reserved envelope 泄漏给业务 handler。

    官方 SDK 2026 也会在协议边界“lift”这些 wire-only 字段，
    业务 handler 通常不应该把它们当普通业务参数处理。
    """
    clean = dict(params or {})
    clean.pop("_meta", None)
    return clean


def header_value(
    headers: Mapping[str, str],
    name: str,
) -> str | None:
    """HTTP header 名大小写不敏感，做一个最小兼容读取。"""
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


# ---------------------------------------------------------------------------
# 9. Tool result 标准化
# ---------------------------------------------------------------------------

def text_result(
    value: Any,
    *,
    structured: Any = _NO_STRUCTURED_CONTENT,
    is_error: bool = False,
) -> ToolResult:
    """把任意 Python 值包装成 MCP text content。

    如果 value 不是 str，就先稳定 JSON 序列化。
    `sort_keys=True` 有利于测试确定性。
    """
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

    return ToolResult(
        content=[{"type": "text", "text": text}],
        structured_content=structured,
        is_error=is_error,
    )


def normalize_tool_result(value: Any) -> dict[str, Any]:
    """把常见 Python handler 返回值统一成 MCP CallToolResult。"""
    if isinstance(value, ToolResult):
        return value.to_object()

    # 对任意 JSON-like 值都可以同时给出文本和 structuredContent。
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return text_result(value, structured=value).to_object()

    # 其他 Python 对象只提供文本表示，避免伪造 structured JSON。
    return text_result(value).to_object()


# ---------------------------------------------------------------------------
# 10. 教学版 JSON Schema 校验器
# ---------------------------------------------------------------------------

def validate_basic_json_schema(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str = "$",
) -> None:
    """验证 Mini-MCP 所需的 JSON Schema 小子集。

    真实 MCP 2026 支持完整 JSON Schema 2020-12。
    生产代码应该使用标准兼容 validator（如 jsonschema / Ajv）。

    这里仅覆盖：
    - type
    - object.properties
    - required
    - additionalProperties=false
    - array.items
    - enum
    - minimum
    - minLength

    目的不是“自己重写 JSON Schema”，而是帮助学习：
    Tool schema 不是 prompt 文本，而是协议级机器可验证契约。
    """

    schema_type = schema.get("type")

    type_matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }

    if (
        isinstance(schema_type, str)
        and not type_matches.get(schema_type, True)
    ):
        raise JsonRpcError(
            INVALID_PARAMS,
            "Tool arguments do not match inputSchema",
            {"path": path, "expected": schema_type},
        )

    if "enum" in schema and value not in schema["enum"]:
        raise JsonRpcError(
            INVALID_PARAMS,
            "Tool argument is not one of the allowed values",
            {"path": path, "allowed": schema["enum"]},
        )

    if isinstance(value, dict):
        required = schema.get("required", [])
        missing = [
            name
            for name in required
            if name not in value
        ]
        if missing:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Required tool arguments are missing",
                {"path": path, "missing": missing},
            )

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for name, child_schema in properties.items():
                if name in value and isinstance(child_schema, dict):
                    validate_basic_json_schema(
                        value[name],
                        child_schema,
                        path=f"{path}.{name}",
                    )

        if (
            schema.get("additionalProperties") is False
            and isinstance(properties, dict)
        ):
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "Unknown tool arguments are not allowed",
                    {"path": path, "unknown": unknown},
                )

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_basic_json_schema(
                    item,
                    item_schema,
                    path=f"{path}[{index}]",
                )

    if isinstance(value, str) and isinstance(
        schema.get("minLength"),
        int,
    ):
        if len(value) < schema["minLength"]:
            raise JsonRpcError(
                INVALID_PARAMS,
                "Tool argument is shorter than minLength",
                {
                    "path": path,
                    "minimum": schema["minLength"],
                },
            )

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        minimum = schema.get("minimum")
        if (
            isinstance(minimum, (int, float))
            and value < minimum
        ):
            raise JsonRpcError(
                INVALID_PARAMS,
                "Tool argument is below minimum",
                {"path": path, "minimum": minimum},
            )
