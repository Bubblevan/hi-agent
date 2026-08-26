"""
Mini-MCP 教学包。

这个包的目标不是替代官方 MCP SDK，而是用尽量少的代码，
把 2026-07-28 这一版 MCP 最值得理解的几个“协议骨架”亲手走一遍：

1. JSON-RPC 2.0 请求 / 响应；
2. 2026 modern era 的“无 initialize、无协议级 session”；
3. 每个请求都携带协议版本、客户端能力等 `_meta` 信封；
4. `server/discover` 的可选能力发现；
5. `tools/list` 的确定性顺序、分页与缓存提示；
6. `tools/call` 的工具调用、JSON Schema 参数校验；
7. Streamable HTTP 下的 `MCP-Protocol-Version` / `Mcp-Method` / `Mcp-Name` 路由头。

刻意没有实现的内容包括：
- Resources / Prompts；
- MRTR（Multi Round-Trip Requests）完整驱动；
- `subscriptions/listen`；
- OAuth / CIMD / 企业授权；
- `x-mcp-header` → `Mcp-Param-*` 参数镜像；
- 完整 JSON Schema 2020-12；
- 旧版 2025-era initialize/session 兼容层。

因此它是“教学用最小实现”，不是生产 SDK。
"""

from .client import MiniMCPClient, MiniMCPHTTPClient
from .protocol import (
    JSONRPC_VERSION,
    PROTOCOL_VERSION,
    CachePolicy,
    JsonRpcError,
    Tool,
    ToolResult,
)
from .server import MiniMCPHTTPServer, MiniMCPServer, run_stdio
from .mrtr import (
    HMACRequestStateCodec,
    InputRequest,
    InputRequired,
    MiniMRTRClient,
    MiniMRTRServer,
    MRTRInputRequiredError,
    MRTRRoundLimitError,
)

# __all__ 明确声明这个教学包希望暴露给外部使用者的公共 API。
# 这样 `from mini_mcp import *` 时不会意外暴露内部辅助函数。
__all__ = [
    "JSONRPC_VERSION",
    "PROTOCOL_VERSION",
    "CachePolicy",
    "JsonRpcError",
    "Tool",
    "ToolResult",
    "MiniMCPClient",
    "MiniMCPHTTPClient",
    "MiniMCPServer",
    "MiniMCPHTTPServer",
    "run_stdio",
    "InputRequest",
    "InputRequired",
    "HMACRequestStateCodec",
    "MiniMRTRClient",
    "MiniMRTRServer",
    "MRTRInputRequiredError",
    "MRTRRoundLimitError",
]
