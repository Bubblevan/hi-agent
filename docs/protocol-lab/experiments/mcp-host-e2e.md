# MCP Host V1 实验记录

日期：2026-08-26

## 实验问题

官方 MCP SDK 发现的工具，能不能不改动原有 Chapter 7 ToolRegistry，
就进入 Hi-Agent 的 Context Selector 和执行链？

## 实验拓扑

    official MCPServer
          ↓ Client(server)
    MCPManager
          ↓
    MCPToolCatalog
          ↓
    MCPToolAdapter
          ↓
    MyToolRegistry
          ↓
    MCPToolSelector + ContextBudget
          ↓
    MCPPolicy
          ↓
    MCPTrace

## 实际代码

    server = MCPServer(name="local-files", version="1.0.0")

    def grep_code(query: str) -> list[str]:
        return [f"mini_mcp/{query}.py"]

    server.tool()(grep_code)

    host = MCPHost()
    host.add_server(MCPServerConfig(
        server_id="filesystem",
        source=server,
    ))

    selection = host.select_tools(
        "搜索项目中所有 Mini-MCP 相关代码"
    )
    execution = host.execute(
        selection.selected[0].canonical_tool_name,
        {"query": "protocol"},
        selected_by="context_selector",
        selection_reason=selection.reasons[
            selection.selected[0].canonical_tool_name
        ],
    )

## 观察结果

Catalog 中的工具名为：

    filesystem.grep_code

但 Adapter 发给 MCP Server 的仍然是：

    grep_code

这说明 canonical name 不是协议名称，而是 Host 的路由名称。两者混在一起，
多 Server 接入时很容易出现“注册成功但调用错 Server”的 bug。

一次成功 trace 至少包含：

    status=completed
    policy_decision=allow
    result_type=complete
    is_error=False

一次危险工具拒绝包含：

    status=policy_denied
    error_kind=policy_denied

并且不会发出 tools/call。

## 失败和修正

### 失败 1：Selector 没选出中文任务对应的 grep_code

最初的 tokenizer 把连续中文当作一个整体 token，英文工具名和中文任务没有
交集。实验版加入了很小的中英 alias bridge，例如“代码”映射到 code，
用于让测试稳定通过。它不是完整中文分词器，未来应替换为项目已有的检索能力。

### 失败 2：Host 可能执行两次工具

如果先调用 Adapter.call_result() 获取 trace，再调用 Adapter.run() 渲染结果，
会重复触发远程工具。修正后由一次 MCPCallResult 同时提供 trace 字段和渲染输入。

### 失败 3：危险级别不能只相信 Server annotation

外部 Server 可能没有提供足够的 annotation。实验 Host 对 delete、exec 等明显
危险动词使用保守 fallback；这仍然只是默认策略，不是安全证明。

## 八卦：为什么 MCP Host 不是“把 SDK 包一层”

很多 MCP demo 到 Client.list_tools() 就结束了，像是“能看到工具”就完成了。
真正的 Host 工作发生在 SDK 之后：工具如何命名、何时进 context、谁能调用、
失败怎样被审计。也正因为这些部分跨越协议、Prompt 和安全边界，官方 SDK
通常不会替你的产品做决定。

另一个容易被忽略的事实是：同一份工具 schema 同时服务两种读者——机器需要
严格的 inputSchema，LLM 需要短而稳定的描述。把原始 schema 原封不动塞进 prompt，
在工具数量增长后，问题会从“调用协议”变成“上下文预算”。

## 结论

这条单 Server 纵向切片满足了 MCP Host 学习的核心目标：

    discover → catalog → adapt → select → policy → call → trace

下一步是补充官方 SDK differential report，然后把这条链路推广到多 Server
和更真实的 Context Selector；完成后才进入 A2A Task/Artifact。

