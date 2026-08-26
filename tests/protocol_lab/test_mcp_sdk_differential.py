from __future__ import annotations

import asyncio

from mcp import Client
from mcp.server import MCPServer

from mini_mcp import MiniMCPClient, MiniMCPServer
from protocols.mcp.manager import MCPManager, MCPServerConfig


def make_mini_server():
    server = MiniMCPServer(name="same-files", version="1.0.0")
    server.register(
        "grep_code",
        lambda arguments: {
            "result": [f"mini_mcp/{arguments['query']}.py"]
        },
        description="Search source code",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    )
    return server


def make_official_server():
    server = MCPServer(name="same-files", version="1.0.0")

    def grep_code(query: str) -> list[str]:
        return [f"mini_mcp/{query}.py"]

    server.tool()(grep_code)
    return server


def test_mini_and_official_sdk_agree_on_core_tool_contract():
    mini = MiniMCPClient(make_mini_server())
    mini_tools = mini.list_tools()["tools"]
    mini_result = mini.call_tool("grep_code", {"query": "protocol"})

    async def official_call():
        async with Client(make_official_server()) as client:
            tools = await client.list_tools()
            result = await client.call_tool(
                "grep_code",
                {"query": "protocol"},
            )
            return tools.model_dump(by_alias=True), result.model_dump(by_alias=True)

    official_tools, official_result = asyncio.run(official_call())

    assert [tool["name"] for tool in mini_tools] == [
        tool["name"] for tool in official_tools["tools"]
    ]
    assert mini_result["structuredContent"] == official_result["structuredContent"]
    assert mini_result.get("isError", False) is False
    assert official_result.get("isError", False) is False


def test_host_manager_normalizes_official_sdk_identity_and_call():
    manager = MCPManager(
        MCPServerConfig(
            server_id="filesystem",
            source=make_official_server(),
        )
    )

    discovered = manager.discover()
    tools = manager.list_tools()
    result = manager.call_tool("grep_code", {"query": "protocol"})

    assert discovered["serverInfo"]["name"] == "same-files"
    assert tools["tools"][0]["name"] == "grep_code"
    assert result.structured_content == {
        "result": ["mini_mcp/protocol.py"]
    }
