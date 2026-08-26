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
        └── mini_a2a/
            └── AgentCard、Message、Task、Artifact 教学 contract

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
contract。官方 A2A SDK 接入应当在未来单独增加 adapter，而不是把 SDK 代码塞进
mini_a2a。

