from __future__ import annotations

import unittest

from protocols.mcp.mini_mcp import (
    HMACRequestStateCodec,
    InputRequest,
    InputRequired,
    MiniMRTRClient,
    MiniMRTRServer,
)
from protocols.mcp.mini_mcp.protocol import (
    INVALID_PARAMS,
    META_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    make_request,
)


class MiniMRTRTests(unittest.TestCase):
    def test_first_round_is_input_required_and_final_round_is_complete(self) -> None:
        codec = HMACRequestStateCodec(b"test-secret")
        observed: list[tuple[dict, object]] = []

        server = MiniMRTRServer(
            name="confirmation-server",
            request_state_codec=codec,
        )

        def delete_file(arguments, input_responses, state):
            if not input_responses:
                return InputRequired(
                    {
                        "confirm": InputRequest(
                            method="elicitation/create",
                            params={
                                "mode": "form",
                                "message": "Delete the file?",
                                "requestedSchema": {
                                    "type": "object",
                                    "properties": {
                                        "confirm": {"type": "boolean"},
                                    },
                                },
                            },
                        )
                    },
                    request_state=codec.mint(
                        {"phase": "awaiting-confirmation", "path": arguments["path"]}
                    ),
                )

            observed.append((dict(input_responses), state))
            accepted = input_responses["confirm"]
            return {
                "deleted": accepted.get("action") == "accept",
                "path": arguments["path"],
            }

        server.register(
            "delete_file",
            delete_file,
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "deleted": {"type": "boolean"},
                    "path": {"type": "string"},
                },
                "required": ["deleted", "path"],
            },
        )

        first = server.handle(
            make_request(
                1,
                "tools/call",
                {
                    "name": "delete_file",
                    "arguments": {"path": "notes.txt"},
                },
            )
        )
        self.assertEqual(first["result"]["resultType"], "input_required")
        self.assertIn("confirm", first["result"]["inputRequests"])
        self.assertIn("requestState", first["result"])

        client = MiniMRTRClient(server)
        result = client.call_tool(
            "delete_file",
            {"path": "notes.txt"},
            input_responder=lambda key, request: {
                "action": "accept",
                "content": {"confirm": True},
            },
        )

        self.assertEqual(result["structuredContent"]["deleted"], True)
        self.assertEqual(result["structuredContent"]["path"], "notes.txt")
        self.assertEqual(observed[0][0]["confirm"]["action"], "accept")
        self.assertEqual(
            observed[0][1],
            {"phase": "awaiting-confirmation", "path": "notes.txt"},
        )

    def test_input_responses_are_replaced_each_round(self) -> None:
        codec = HMACRequestStateCodec(b"test-secret")
        observed_keys: list[list[str]] = []
        server = MiniMRTRServer(request_state_codec=codec)

        def two_step(arguments, input_responses, state):
            observed_keys.append(sorted(input_responses))
            if state is None:
                return InputRequired(
                    {"first": InputRequest("elicitation/create", {"message": "First?"})},
                    request_state=codec.mint({"phase": 1}),
                )
            if state["phase"] == 1:
                return InputRequired(
                    {"second": InputRequest("elicitation/create", {"message": "Second?"})},
                    request_state=codec.mint({"phase": 2}),
                )
            return {"done": True}

        server.register("two_step", two_step)
        result = MiniMRTRClient(server).call_tool(
            "two_step",
            input_responder=lambda key, request: {
                "action": "accept",
                "content": {key: True},
            },
        )

        self.assertEqual(result["structuredContent"], {"done": True})
        self.assertEqual(observed_keys, [[], ["first"], ["second"]])

    def test_tampered_request_state_is_rejected(self) -> None:
        codec = HMACRequestStateCodec(b"test-secret")
        server = MiniMRTRServer(request_state_codec=codec)
        server.register(
            "needs_confirmation",
            lambda arguments, input_responses, state: InputRequired(
                {"confirm": InputRequest("elicitation/create", {"message": "Confirm?"})},
                request_state=codec.mint({"phase": "confirm"}),
            ),
        )

        first = server.handle(
            make_request(
                1,
                "tools/call",
                {"name": "needs_confirmation", "arguments": {}},
            )
        )
        state = first["result"]["requestState"]
        tampered = state[:-1] + ("A" if state[-1] != "A" else "B")

        retry = server.handle(
            make_request(
                2,
                "tools/call",
                {
                    "name": "needs_confirmation",
                    "arguments": {},
                    "inputResponses": {
                        "confirm": {"action": "accept", "content": {}},
                    },
                    "requestState": tampered,
                },
            )
        )
        self.assertEqual(retry["error"]["code"], INVALID_PARAMS)

    def test_mrtr_request_uses_modern_protocol_metadata(self) -> None:
        server = MiniMRTRServer()
        captured = {}

        def echo(arguments, input_responses, state):
            captured.update(arguments)
            return {"ok": True}

        server.register("echo", echo)
        response = server.handle(
            make_request(
                1,
                "tools/call",
                {"name": "echo", "arguments": {}},
            )
        )
        self.assertEqual(response["result"]["resultType"], "complete")
        self.assertEqual(captured, {})

    def test_unsupported_request_version_is_rejected(self) -> None:
        server = MiniMRTRServer()
        request = make_request(1, "tools/call", {"name": "x", "arguments": {}})
        request["params"]["_meta"][META_PROTOCOL_VERSION] = "2025-11-25"
        response = server.handle(request)
        self.assertEqual(response["error"]["code"], -32022)
        self.assertEqual(PROTOCOL_VERSION, "2026-07-28")


if __name__ == "__main__":
    unittest.main()
