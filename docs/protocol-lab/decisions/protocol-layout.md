# Protocol Package Layout Decision

日期：2026-08-26

## 问题

原来的目录同时出现：

    D:\MyLab\hi-agent\mini_mcp
    D:\MyLab\hi-agent\protocols\mcp
    D:\MyLab\hi-agent\protocols\a2a_lab

它们并不是重复实现，但目录层级没有表达职责，容易产生三个误解：

1. 以为 protocols/mcp 是 Mini-MCP 的第二份实现；
2. 以为 Mini-A2A 是生产 A2A SDK；
3. 以为协议实验和 Hi-Agent runtime integration 应该放在同一层。

## 最终结构

    protocols/
    ├── mcp/
    │   ├── mini_mcp/
    │   │   ├── protocol.py
    │   │   ├── client.py
    │   │   ├── server.py
    │   │   └── mrtr.py
    │   └── host/
    │       ├── manager.py
    │       ├── catalog.py
    │       ├── adapter.py
    │       ├── policy.py
    │       ├── host.py
    │       └── __init__.py
    └── a2a/
        ├── mini_a2a/
        │   ├── models.py
        │   ├── protocol.py
        │   ├── client.py
        │   ├── executor.py
        │   └── __init__.py
        └── integration/
            ├── server.py
            ├── client.py
            └── __init__.py

## 三种职责

### 1. 协议实验

    protocols/mcp/mini_mcp
    protocols/a2a/mini_a2a

这两个目录只回答协议学习问题：

- wire/model 长什么样；
- 最小生命周期是什么；
- 错误和状态转换怎样约束；
- raw contract test 怎样写。

它们不是官方 SDK 的替代品，也不是 Hi-Agent Agent loop 的默认依赖。

官方 A2A SDK 集成位于 protocols/a2a/integration。它只拥有 adapter、route
assembly 和官方类型的使用代码；它不把官方 SDK 的实现复制进学习夹具。

### 2. 官方 SDK 集成

    protocols/mcp/host
    protocols/a2a/integration

这里使用官方 MCP Python SDK，把外部 Server 接入 Hi-Agent。这里的代码拥有：

- Manager；
- Catalog；
- Adapter；
- Policy；
- Host composition。

它不重新实现 JSON-RPC、transport 或 MCP schema validator。

### 3. 通用 Agent Runtime

    tools/
    context/
    runtime/

这些目录不属于某个协议：

- tools/ 保存 Hi-Agent 自己的工具抽象和 ToolRegistry；
- context/ 保存上下文预算、选择和编译；
- runtime/ 保存执行和观测。

MCP Host 和未来 A2A adapter 可以调用它们，但不能反过来让通用层依赖某个协议
实验包。

## 导入约定

公开入口：

    from protocols.mcp.mini_mcp import MiniMCPServer
    from protocols.mcp.host import MCPHost
    from protocols.a2a.mini_a2a import MiniA2AServer

不建议业务代码依赖：

    from protocols.mcp.host.host import MCPHost
    from protocols.mcp.host.manager import MCPManager

后者是包内部文件路径，测试可以使用，业务入口优先从 package export 导入。

## 迁移映射

    mini_mcp/*
      → protocols/mcp/mini_mcp/*

    protocols/mcp/{manager,catalog,adapter,policy,host}.py
      → protocols/mcp/host/{manager,catalog,adapter,policy,host}.py

    protocols/a2a_lab/*
      → protocols/a2a/mini_a2a/*

旧目录不保留兼容副本。否则结构检查时仍然会出现两个真相来源。

## 判断规则

以后新增文件前先问：

    这是手写协议 contract 吗？
      → protocols/<protocol>/mini_<protocol>/

    这是官方 SDK 到 Hi-Agent 的适配吗？
      → protocols/<protocol>/host/ 或 adapter/

    这是通用的工具、上下文、执行或观测能力吗？
      → tools/、context/、runtime/

如果一个文件同时回答两个问题，应优先拆开，而不是继续向现有目录堆功能。
