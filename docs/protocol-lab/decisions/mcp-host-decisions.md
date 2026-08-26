# Hi-Agent MCP Host V1 决策记录

## 决策 1：官方 SDK 负责协议，Hi-Agent 负责运行时

官方 Python SDK 负责 transport、JSON-RPC、2026 request envelope、result model、
MRTR round-trip 和协议校验。Hi-Agent 不复制这些实现。

Hi-Agent 负责：

    MCP Manager → Tool Catalog → Tool Adapter → ToolRegistry
        → Context Selector → Policy → Executor → Trace

## 决策 2：先采用单 Server、in-process 测试

第一版用官方 SDK 的 MCPServer + Client(server) 进行 in-process 测试。
这不是把 in-process 当生产 transport，而是让测试稳定验证 Host 的边界。
之后再用同一个 Manager 替换为 StdioServerParameters 或 Streamable HTTP URL。

## 决策 3：兼容现有同步 ToolRegistry

Hi-Agent 现有 MyTool.run 是同步字符串接口，因此 MCPManager 同时提供：

- async_discover、async_list_tools、async_call_tool；
- discover、list_tools、call_tool 同步教学门面。

同步门面在运行中的 async loop 内会显式报错，避免隐藏 event loop 问题。
真正的异步 Agent loop 应该使用 async API。

## 决策 4：canonical name 与 original name 分开保存

内部使用：

    filesystem.grep_code

发给 MCP Server：

    grep_code

两者必须同时保存，便于多 Server 共存、冲突排查和 trace 还原。

## 决策 5：工具 schema 进入 Catalog，不直接进入 Prompt

Context Selector 从 Catalog 检索候选工具，再使用现有 ContextItem 和
select_items() 执行 token budget。Selector 返回 selected、dropped 和 reason，
从而可以比较全量注入与动态选择。

## 决策 6：Policy 在 MCP call 之前执行

read_only 默认放行；write 默认需要确认；dangerous 默认拒绝。
policy_denied 不应该伪装成 MCP tool error，也不应该发出网络请求。

## 当前明确不做

- 多 Server 自动发现；
- OAuth、mTLS 和多租户；
- 完整 tool marketplace；
- 修改旧 MyToolRegistry 的 Chapter 7 行为；
- 继续扩展 Mini-MCP 以替代官方 SDK。

