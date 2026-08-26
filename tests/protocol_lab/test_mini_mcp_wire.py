from __future__ import annotations

import unittest

from protocols.mcp.mini_mcp import (
    PROTOCOL_VERSION,
    CachePolicy,
    MiniMCPClient,
    MiniMCPServer,
)
from protocols.mcp.mini_mcp.protocol import (
    HEADER_MISMATCH,
    META_CLIENT_CAPABILITIES,
    META_PROTOCOL_VERSION,
    make_request,
)


class MiniMCPRawWireContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MiniMCPServer(
            name="wire-server",
            version="2.0.0",
            cache_policy=CachePolicy(ttl_ms=1_000, cache_scope="public"),
            page_size=10,
        )
        self.server.register(
            "list_value",
            lambda args: [1, 2, 3],
            output_schema={
                "type": "array",
                "items": {"type": "integer"},
            },
        )

    def test_request_carries_modern_metadata_on_every_call(self) -> None:
        request = make_request(
            1,
            "server/discover",
            client_info={"name": "wire-test", "version": "1.0"},
            client_capabilities={},
        )
        meta = request["params"]["_meta"]
        self.assertEqual(meta[META_PROTOCOL_VERSION], PROTOCOL_VERSION)
        self.assertEqual(meta[META_CLIENT_CAPABILITIES], {})
        self.assertEqual(meta["io.modelcontextprotocol/clientInfo"]["name"], "wire-test")

    def test_success_wire_has_result_type_and_server_info(self) -> None:
        response = self.server.handle(
            make_request(1, "tools/list"),
            transport="stdio",
        )
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["result"]["resultType"], "complete")
        self.assertEqual(
            response["result"]["_meta"]["io.modelcontextprotocol/serverInfo"],
            {"name": "wire-server", "version": "2.0.0"},
        )

    def test_client_unwrap_consumes_wire_result_type(self) -> None:
        result = MiniMCPClient(self.server).discover()
        self.assertNotIn("resultType", result)
        self.assertEqual(
            result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"],
            "wire-server",
        )

    def test_structured_content_can_be_a_json_array(self) -> None:
        result = MiniMCPClient(self.server).call_tool("list_value")
        self.assertEqual(result["structuredContent"], [1, 2, 3])

    def test_http_header_and_body_version_mismatch_is_header_mismatch(self) -> None:
        request = make_request(1, "server/discover")
        request["params"]["_meta"][META_PROTOCOL_VERSION] = "2025-11-25"
        response = self.server.handle(
            request,
            headers={
                "MCP-Protocol-Version": PROTOCOL_VERSION,
                "Mcp-Method": "server/discover",
            },
            transport="http",
        )
        self.assertEqual(response["error"]["code"], HEADER_MISMATCH)

    def test_http_header_and_body_method_mismatch_is_header_mismatch(self) -> None:
        response = self.server.handle(
            make_request(1, "server/discover"),
            headers={
                "MCP-Protocol-Version": PROTOCOL_VERSION,
                "Mcp-Method": "tools/list",
            },
            transport="http",
        )
        self.assertEqual(response["error"]["code"], HEADER_MISMATCH)


if __name__ == "__main__":
    unittest.main()
