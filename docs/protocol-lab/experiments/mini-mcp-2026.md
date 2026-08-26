# Mini-MCP 2026-07-28 实验说明

## 实验定位

这是 Hi-Agent 的学习型 Mini-MCP，不是生产级 MCP SDK。

实现目标是亲手验证：

    discovery → schema → call → structured result / error

## 对齐的 2026-07-28 核心

本实验实现：

- JSON-RPC 2.0；
- server/discover；
- tools/list；
- tools/call；
- 无 initialize / initialized 握手；
- 无 Mcp-Session-Id；
- stdio / in-process 请求通过 _meta 携带协议版本；
- HTTP 请求通过 MCP-Protocol-Version 携带协议版本；
- HTTP 请求校验 Mcp-Method；
- tools/call 校验 Mcp-Name；
- 工具列表确定性排序；
- tools/list 和 server/discover 返回 ttlMs、cacheScope；
- 工具结果使用 content、可选 structuredContent 和 isError；
- 工具输入使用一个无第三方依赖的 JSON Schema 教学子集校验。

## 明确不实现的部分

- Tasks 扩展；
- OAuth / OIDC；
- mTLS；
- Resources / Prompts；
- 完整 JSON Schema 2020-12 validator；
- 生产级 HTTP 认证、限流、观测和部署；
- 服务器主动请求和长连接会话。

## 关键实验

### 实验一：server/discover

确认现代协议不再先发送 initialize，而是通过 server/discover 获取：

- supportedVersions；
- capabilities；
- instructions；
- serverInfo；
- cache hints。

### 实验二：tools/list

确认：

- 工具按名称稳定排序；
- 结果支持分页；
- 结果携带 ttlMs 和 cacheScope；
- 客户端可以根据 TTL 缓存工具目录。

### 实验三：tools/call

确认：

- 工具参数按 inputSchema 校验；
- 未知工具是 JSON-RPC 层错误；
- 工具执行失败是 result 内的 isError: true；
- 成功调用可以返回 structuredContent。

### 实验四：HTTP 无状态传输

确认：

- 每个请求都自包含；
- 不创建协议级 session；
- 不使用 Mcp-Session-Id；
- 不依赖 GET / DELETE；
- 请求头与 JSON-RPC body 的 method / name 必须一致。

## Mini-MRTR 独立实验

Mini-MRTR 不修改 Mini-MCP 的基础 tools/call 主路径，单独位于：

    mini_mcp/mrtr.py

它演示以下 2026 多轮往返：

    tools/call
        ↓
    resultType=input_required
        ↓
    client 收集 inputResponses
        ↓
    原请求重发，并原样回传 requestState
        ↓
    server 验证 requestState
        ↓
    resultType=complete

当前实现包含：

- InputRequest；
- InputRequired；
- InputResponses 的逐轮替换语义；
- 不透明 requestState 的 HMAC 完整性校验；
- MRTR 最大轮数限制；
- tampered / expired requestState 的协议错误处理。

当前没有实现：

- 完整 elicitation schema；
- sampling 和 roots 的具体输入类型；
- Tasks 与 MRTR 的组合；
- 生产级身份绑定和密钥管理。

## 下一步

Mini-MCP 和 Mini-MRTR 完成后，不继续扩展协议实现。下一阶段应使用官方 MCP SDK，重点实现 Hi-Agent 的：

    MCP Manager
        ↓
    Tool Adapter
        ↓
    Tool Registry
        ↓
    Context Selector
        ↓
    Permission Policy
        ↓
    Trace / Execution
