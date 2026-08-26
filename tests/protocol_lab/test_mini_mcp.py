from __future__ import annotations

import io
import json
import unittest

from protocols.mcp.mini_mcp import (
    PROTOCOL_VERSION,
    CachePolicy,
    MiniMCPClient,
    MiniMCPServer,
    run_stdio,
)
from protocols.mcp.mini_mcp.protocol import HEADER_MISMATCH, INVALID_PARAMS, make_request


class MiniMCPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MiniMCPServer(
            name="test-server",
            version="1.0.0",
            cache_policy=CachePolicy(ttl_ms=30_000, cache_scope="public"),
            page_size=1,
        )
        self.server.register(
            "add",
            lambda args: {"sum": args["a"] + args["b"]},
            description="Add two integers.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        )
        self.server.register(
            "echo",
            lambda args: args["text"],
            description="Echo text.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "minLength": 1}},
                "required": ["text"],
                "additionalProperties": False,
            },
        )

    def test_2026_discovery_has_no_initialize_handshake(self) -> None:
        response = self.server.handle(
            make_request(1, "server/discover"),
            transport="stdio",
        )
        self.assertIn("result", response)
        self.assertEqual(
            response["result"]["supportedVersions"],
            [PROTOCOL_VERSION],
        )
        self.assertIn("ttlMs", response["result"])
        self.assertIn("cacheScope", response["result"])

    def test_wire_result_contains_result_type_and_server_identity(self) -> None:
        response = self.server.handle(
            make_request(1, "server/discover"),
            transport="stdio",
        )
        wire_result = response["result"]
        self.assertEqual(wire_result["resultType"], "complete")
        self.assertEqual(
            wire_result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"],
            "test-server",
        )

    def test_tools_are_deterministic_and_paginated(self) -> None:
        client = MiniMCPClient(self.server)
        result = client.list_tools()
        self.assertEqual([tool["name"] for tool in result["tools"]], ["add", "echo"])
        self.assertEqual(result["ttlMs"], 30_000)
        self.assertEqual(result["cacheScope"], "public")

    def test_tool_call_returns_structured_content(self) -> None:
        client = MiniMCPClient(self.server)
        result = client.call_tool("add", {"a": 2, "b": 3})
        self.assertEqual(result["structuredContent"], {"sum": 5})
        self.assertEqual(result["content"][0]["type"], "text")

    def test_tool_failure_is_inside_result(self) -> None:
        client = MiniMCPClient(self.server)
        result = client.call_tool("echo", {"text": ""})
        self.assertTrue(result["isError"])
        self.assertIn("minLength", result["content"][0]["text"])

    def test_unknown_tool_is_protocol_error(self) -> None:
        response = self.server.handle(
            make_request(
                1,
                "tools/call",
                {"name": "missing", "arguments": {}},
            )
        )
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_http_headers_are_checked(self) -> None:
        request = make_request(
            1,
            "tools/call",
            {"name": "add", "arguments": {"a": 1, "b": 2}},
        )
        response = self.server.handle(
            request,
            headers={
                "MCP-Protocol-Version": PROTOCOL_VERSION,
                "Mcp-Method": "tools/call",
                "Mcp-Name": "wrong-name",
            },
            transport="http",
        )
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], HEADER_MISMATCH)

    def test_null_is_a_valid_structured_content_value(self) -> None:
        self.server.register(
            "null_value",
            lambda args: None,
            output_schema={"type": "null"},
        )
        client = MiniMCPClient(self.server)
        result = client.call_tool("null_value")
        self.assertIn("structuredContent", result)
        self.assertIsNone(result["structuredContent"])

    def test_stdio_is_newline_delimited_json(self) -> None:
        incoming = json.dumps(make_request(1, "server/discover")) + "\n"
        output = io.StringIO()
        run_stdio(self.server, io.StringIO(incoming), output)
        decoded = json.loads(output.getvalue())
        self.assertEqual(decoded["result"]["supportedVersions"], [PROTOCOL_VERSION])


if __name__ == "__main__":
    unittest.main()
