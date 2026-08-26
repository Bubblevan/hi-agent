# Protocols

本目录只放协议相关代码，并按“协议族”和“实现职责”分层。

## 当前结构

    protocols/
    ├── mcp/
    │   ├── mini_mcp/
    │   │   └── 手写 MCP 2026 wire contract、MRTR 和 raw fixture
    │   └── host/
    │       └── 官方 MCP SDK 之上的 Hi-Agent Host 集成
    └── a2a/
        ├── mini_a2a/
        │   └── AgentCard、Message、Task、Artifact 教学 contract
        └── integration/
            └── 官方 a2a-sdk v1 的 Coding Agent Server / Research Agent Client

## 怎么判断代码应该放哪里

    手写协议、状态机、wire/model 实验
      → protocols/<protocol>/mini_<protocol>/

    官方 SDK 到 Hi-Agent 的适配、目录、策略、Host
      → protocols/<protocol>/host/

    通用工具、上下文、执行和观测
      → tools/、context/、runtime/

## 当前三个包的边界

### protocols.mcp.mini_mcp

学习夹具。它可以被 raw wire tests 和 differential tests 使用，但不作为
Hi-Agent 默认 runtime。

### protocols.mcp.host

MCP Host 集成。它使用官方 MCP Python SDK，负责 Manager、Catalog、Adapter、
Policy 和 Host composition。

### protocols.a2a.mini_a2a

Mini-A2A 学习夹具。它只覆盖五个核心对象、最小 Task 生命周期和本地 stream
contract。它不承担网络传输和生产认证。

### protocols.a2a.integration

官方 A2A SDK 集成。这里使用 SDK 1.x 的 proto types、Agent Card route、
JSON-RPC route、DefaultRequestHandler、TaskUpdater 和 Client；它把 Coding
Agent 接到现有 MCP Host，但不把 SDK 实现复制到 mini_a2a。
