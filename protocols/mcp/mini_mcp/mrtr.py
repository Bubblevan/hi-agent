"""Standalone Mini-MRTR experiment for MCP revision 2026-07-28.

This module deliberately lives beside Mini-MCP instead of changing the normal
tools/call path. It demonstrates the modern stateless pattern:

    tools/call
      -> resultType=input_required
      -> client collects inputResponses
      -> original call is retried with requestState
      -> resultType=complete

It is an educational implementation, not a production authorization or
request-state subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import hmac
import inspect
import json
import time
from typing import Any, Callable, Mapping

from .protocol import (
    HEADER_MISMATCH,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    META_CLIENT_CAPABILITIES,
    META_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    UNSUPPORTED_PROTOCOL_VERSION,
    JsonRpcError,
    make_error,
    make_request,
    normalize_tool_result,
    parse_json,
    request_meta,
    strip_meta,
    validate_basic_json_schema,
    validate_request,
    header_value,
)


class MRTRRoundLimitError(RuntimeError):
    """The client received too many input_required rounds."""


class MRTRInputRequiredError(RuntimeError):
    """The caller did not provide a responder for an input-required result."""

    def __init__(self, input_requests: Mapping[str, Any]):
        self.input_requests = dict(input_requests)
        super().__init__(
            "MRTR requires input responses for: "
            + ", ".join(sorted(self.input_requests))
        )


@dataclass(frozen=True)
class InputRequest:
    """A small generic server-to-client input request."""

    method: str
    params: dict[str, Any]

    def to_object(self) -> dict[str, Any]:
        return {"method": self.method, "params": dict(self.params)}


class InputRequired(Exception):
    """Raised by a tool handler when another input round is required."""

    def __init__(
        self,
        input_requests: Mapping[str, InputRequest | Mapping[str, Any]],
        *,
        request_state: str | None = None,
    ) -> None:
        self.input_requests = dict(input_requests)
        self.request_state = request_state
        super().__init__("additional client input is required")


@dataclass
class MRTRTool:
    name: str
    handler: Callable[
        [dict[str, Any], Mapping[str, Any], Any],
        Any,
    ]
    description: str = ""
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    def definition(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "inputSchema": self.input_schema
            or {"type": "object", "properties": {}},
        }
        if self.description:
            result["description"] = self.description
        if self.output_schema is not None:
            result["outputSchema"] = self.output_schema
        return result


class HMACRequestStateCodec:
    """A minimal integrity-protected opaque requestState codec.

    The client treats the token as opaque. The server verifies it before
    passing the decoded payload to a handler. This signs, but does not encrypt,
    the payload.
    """

    def __init__(
        self,
        secret: bytes,
        *,
        ttl_seconds: int | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not secret:
            raise ValueError("secret must not be empty")
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.secret = secret
        self.ttl_seconds = ttl_seconds
        self.clock = clock

    def mint(self, payload: Mapping[str, Any]) -> str:
        envelope: dict[str, Any] = {"payload": dict(payload)}
        if self.ttl_seconds is not None:
            envelope["exp"] = int(self.clock()) + self.ttl_seconds
        body = self._encode_json(envelope)
        signature = hmac.new(
            self.secret,
            body,
            hashlib.sha256,
        ).digest()
        return self._b64(body) + "." + self._b64(signature)

    def verify(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or "." not in token:
            raise JsonRpcError(INVALID_PARAMS, "Invalid requestState")
        encoded_body, encoded_signature = token.split(".", 1)
        try:
            body = base64.urlsafe_b64decode(
                self._pad(encoded_body)
            )
            signature = base64.urlsafe_b64decode(
                self._pad(encoded_signature)
            )
        except Exception as exc:
            raise JsonRpcError(INVALID_PARAMS, "Invalid requestState") from exc

        expected = hmac.new(
            self.secret,
            body,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise JsonRpcError(INVALID_PARAMS, "Invalid requestState")

        try:
            envelope = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JsonRpcError(INVALID_PARAMS, "Invalid requestState") from exc

        if not isinstance(envelope, dict) or not isinstance(
            envelope.get("payload"),
            dict,
        ):
            raise JsonRpcError(INVALID_PARAMS, "Invalid requestState")

        expires_at = envelope.get("exp")
        if isinstance(expires_at, int) and self.clock() >= expires_at:
            raise JsonRpcError(INVALID_PARAMS, "Expired requestState")

        return dict(envelope["payload"])

    @staticmethod
    def _encode_json(value: Mapping[str, Any]) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _b64(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _pad(value: str) -> str:
        return value + "=" * (-len(value) % 4)


class MiniMRTRServer:
    """A stateless server supporting only the MRTR tools/call experiment."""

    def __init__(
        self,
        *,
        name: str = "hi-agent-mini-mrtr",
        version: str = "0.1.0",
        request_state_codec: HMACRequestStateCodec | None = None,
    ) -> None:
        self.name = name
        self.version = version
        self.request_state_codec = request_state_codec
        self._tools: dict[str, MRTRTool] = {}

    def register(
        self,
        name: str,
        handler: Callable[[dict[str, Any], Mapping[str, Any], Any], Any],
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> None:
        if not name or "/" in name:
            raise ValueError("tool name must be non-empty and must not contain '/'")
        if name in self._tools:
            raise ValueError(f"tool already registered: {name}")
        self._tools[name] = MRTRTool(
            name=name,
            handler=handler,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
        )

    def handle(
        self,
        raw_request: str | bytes | Mapping[str, Any],
        *,
        headers: Mapping[str, str] | None = None,
        transport: str = "stdio",
    ) -> dict[str, Any]:
        request_id: Any = None
        try:
            request = parse_json(raw_request)
            request_id = request.get("id")
            validate_request(request)
            self._validate_modern_request(request, headers or {}, transport)
            result = self._dispatch(request)
            result = self._stamp_server_info(result)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except JsonRpcError as exc:
            return make_error(request_id, exc)
        except Exception as exc:
            return make_error(
                request_id,
                JsonRpcError(INTERNAL_ERROR, "Internal error", str(exc)),
            )

    def _validate_modern_request(
        self,
        request: Mapping[str, Any],
        headers: Mapping[str, str],
        transport: str,
    ) -> None:
        meta = request_meta(request)
        body_version = meta.get(META_PROTOCOL_VERSION)

        if transport == "http":
            header_version = header_value(
                headers,
                "MCP-Protocol-Version",
            )
            if not header_version or header_version != body_version:
                raise JsonRpcError(
                    HEADER_MISMATCH,
                    "MCP-Protocol-Version header must match request _meta",
                    {"header": header_version, "body": body_version},
                )
            if header_value(headers, "Mcp-Method") != request["method"]:
                raise JsonRpcError(
                    HEADER_MISMATCH,
                    "Mcp-Method must match the JSON-RPC method",
                )
            if request["method"] == "tools/call":
                params = strip_meta(request.get("params"))
                if header_value(headers, "Mcp-Name") != params.get("name"):
                    raise JsonRpcError(
                        HEADER_MISMATCH,
                        "Mcp-Name must match tools/call params.name",
                    )

        if body_version != PROTOCOL_VERSION:
            raise JsonRpcError(
                UNSUPPORTED_PROTOCOL_VERSION,
                "Mini-MRTR requires protocol revision 2026-07-28",
                {"received": body_version, "supported": [PROTOCOL_VERSION]},
            )

        capabilities = meta.get(META_CLIENT_CAPABILITIES)
        if not isinstance(capabilities, dict):
            raise JsonRpcError(
                INVALID_PARAMS,
                "clientCapabilities must be an object",
            )

    def _dispatch(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if request["method"] != "tools/call":
            raise JsonRpcError(
                METHOD_NOT_FOUND,
                "Mini-MRTR only implements tools/call",
            )
        return self._call_tool(strip_meta(request.get("params")))

    def _call_tool(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        input_responses = params.get("inputResponses", {})
        request_state = params.get("requestState")

        if not isinstance(name, str) or not name:
            raise JsonRpcError(INVALID_PARAMS, "tools/call requires params.name")
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "arguments must be an object")
        if not isinstance(input_responses, dict):
            raise JsonRpcError(INVALID_PARAMS, "inputResponses must be an object")
        if request_state is not None and not isinstance(request_state, str):
            raise JsonRpcError(INVALID_PARAMS, "requestState must be a string")

        tool = self._tools.get(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name}")

        decoded_state: Any = None
        if request_state is not None:
            if self.request_state_codec is None:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "requestState validation is not configured",
                )
            # requestState is an untrusted opaque token. Invalid or expired
            # state is a protocol error, not a tool-level isError result.
            decoded_state = self.request_state_codec.verify(request_state)

        try:
            validate_basic_json_schema(
                arguments,
                tool.input_schema
                or {"type": "object", "properties": {}},
            )
            value = tool.handler(
                arguments,
                input_responses,
                decoded_state,
            )
            if inspect.isawaitable(value):
                raise RuntimeError("Mini-MRTR handlers must be synchronous")

            if isinstance(value, InputRequired):
                return self._input_required_result(value)

            result = normalize_tool_result(value)
            if (
                tool.output_schema is not None
                and "structuredContent" in result
            ):
                validate_basic_json_schema(
                    result["structuredContent"],
                    tool.output_schema,
                )
            return result
        except InputRequired as exc:
            return self._input_required_result(exc)
        except JsonRpcError as exc:
            message = exc.message if exc.data is None else f"{exc.message}: {exc.data}"
            return normalize_tool_result(message) | {"isError": True}
        except Exception as exc:
            return normalize_tool_result(str(exc)) | {"isError": True}

    def _input_required_result(
        self,
        value: InputRequired,
    ) -> dict[str, Any]:
        requests: dict[str, Any] = {}
        for key, request in value.input_requests.items():
            if isinstance(request, InputRequest):
                requests[key] = request.to_object()
            elif isinstance(request, Mapping):
                requests[key] = dict(request)
            else:
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Invalid input request: {key}",
                )

        result: dict[str, Any] = {
            "resultType": "input_required",
            "inputRequests": requests,
        }
        if value.request_state is not None:
            result["requestState"] = value.request_state
        return result

    def _stamp_server_info(
        self,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        stamped = dict(result)
        meta = dict(stamped.get("_meta") or {})
        meta.setdefault(
            "io.modelcontextprotocol/serverInfo",
            {"name": self.name, "version": self.version},
        )
        stamped["_meta"] = meta
        stamped.setdefault("resultType", "complete")
        return stamped


class MiniMRTRClient:
    """A client driver that automatically completes MRTR input rounds."""

    def __init__(
        self,
        server: MiniMRTRServer,
        *,
        client_name: str = "hi-agent-mini-mrtr-client",
        client_version: str = "0.1.0",
        client_capabilities: Mapping[str, Any] | None = None,
    ) -> None:
        self.server = server
        self.client_name = client_name
        self.client_version = client_version
        self.client_capabilities = dict(client_capabilities or {})
        self._counter = 0

    def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._counter += 1
        request = make_request(
            self._counter,
            method,
            params,
            client_info={
                "name": self.client_name,
                "version": self.client_version,
            },
            client_capabilities=self.client_capabilities,
        )
        return self.server.handle(request)

    def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        input_responder: Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
        | None = None,
        max_rounds: int = 10,
    ) -> dict[str, Any]:
        if max_rounds < 0:
            raise ValueError("max_rounds must be non-negative")

        original_arguments = dict(arguments or {})
        params: dict[str, Any] = {
            "name": name,
            "arguments": original_arguments,
        }

        for round_index in range(max_rounds + 1):
            response = self.request("tools/call", params)
            if "error" in response:
                error = response["error"]
                raise JsonRpcError(
                    int(error.get("code", INVALID_PARAMS)),
                    str(error.get("message", "MRTR request failed")),
                    error.get("data"),
                )

            result = response.get("result")
            if not isinstance(result, dict):
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "MRTR result must be an object",
                )

            result_type = result.get("resultType")
            if result_type == "complete":
                clean = dict(result)
                clean.pop("resultType", None)
                return clean

            if result_type != "input_required":
                raise JsonRpcError(
                    INVALID_PARAMS,
                    f"Unexpected MRTR resultType: {result_type!r}",
                )

            if round_index >= max_rounds:
                raise MRTRRoundLimitError(
                    f"MRTR exceeded max_rounds={max_rounds}"
                )

            input_requests = result.get("inputRequests", {})
            if not isinstance(input_requests, dict):
                raise JsonRpcError(
                    INVALID_PARAMS,
                    "inputRequests must be an object",
                )
            if input_requests and input_responder is None:
                raise MRTRInputRequiredError(input_requests)

            input_responses: dict[str, Any] = {}
            if input_responder is not None:
                for key, request_object in input_requests.items():
                    response_object = input_responder(key, request_object)
                    if not isinstance(response_object, Mapping):
                        raise TypeError(
                            f"input responder returned non-object for {key}"
                        )
                    input_responses[key] = dict(response_object)

            # inputResponses are per-round and are deliberately replaced,
            # never accumulated. requestState is echoed byte-for-byte.
            params = {
                "name": name,
                "arguments": original_arguments,
                "inputResponses": input_responses,
            }
            if "requestState" in result:
                params["requestState"] = result["requestState"]

        raise AssertionError("unreachable")
