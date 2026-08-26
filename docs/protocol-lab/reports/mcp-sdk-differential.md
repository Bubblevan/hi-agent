# Mini-MCP 与官方 Python SDK 差分报告

日期：2026-08-26
SDK：mcp 2.1.1

## 比较对象

- Mini-MCP：D:\MyLab\hi-agent\mini_mcp
- 官方 SDK：mcp 2.1.1 的 Client 和 MCPServer
- 相同能力：grep_code(query) → {"result": ["mini_mcp/protocol.py"]}

## 比较代码

    mini = MiniMCPClient(make_mini_server())
    mini_tools = mini.list_tools()["tools"]
    mini_result = mini.call_tool(
        "grep_code",
        {"query": "protocol"},
    )

    async with Client(make_official_server()) as client:
        tools = await client.list_tools()
        result = await client.call_tool(
            "grep_code",
            {"query": "protocol"},
        )

## 结果

| Contract | Mini-MCP | 官方 SDK | 结论 |
|---|---|---|---|
| tool name | grep_code | grep_code | 一致 |
| input schema | object/query/string | object/query/string | 一致 |
| structured result | object/result=list[str] | object/result=list[str] | 一致 |
| isError | false | false | 一致 |
| resultType | complete | complete | 一致 |
| transport | direct/stdlib teaching transport | SDK transport | 实现不同 |
| pagination | explicit mini cursor | SDK cursor API | 语义一致，细节交给 SDK |
| auth | 未实现 | SDK 支持扩展 | Mini-MCP 教学省略 |

## 差分原则

比较的是 Host 依赖的语义 contract，不是 JSON 字节序列。动态 request id、
SDK 内部 model 类型和 transport framing 不应成为 Mini-MCP 的复制目标。

## 八卦：为什么版本号要写进实验报告

SDK 的类型和生命周期 API 会演进，尤其是协议从旧版 session/handshake 路径
走向 2026-07-28 modern path 后，很多“看起来只是初始化代码”的示例已经不再
代表当前默认行为。把版本写进报告，未来回看时才知道差异来自自己的代码，
还是来自 SDK 变更。

## 结论

Mini-MCP 足以作为 wire contract fixture，但不再继续扩展为 SDK 替代品。
Hi-Agent 的新增价值位于 SDK 之上：

    catalog → selection → policy → registry → trace
