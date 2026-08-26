"""Small structured trace objects for MCP Host experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class MCPTrace:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    request_id: str = field(default_factory=lambda: uuid4().hex)
    server_id: str = ""
    canonical_tool_name: str = ""
    original_tool_name: str = ""
    selected_by: str = ""
    selection_reason: str = ""
    policy_decision: str = ""
    result_type: str | None = None
    is_error: bool | None = None
    status: str = "started"
    duration_ms: float | None = None
    error_kind: str | None = None
    _started: float = field(default_factory=monotonic, repr=False)

    def finish(
        self,
        *,
        status: str,
        result_type: str | None = None,
        is_error: bool | None = None,
        error_kind: str | None = None,
    ) -> "MCPTrace":
        self.status = status
        self.result_type = result_type
        self.is_error = is_error
        self.error_kind = error_kind
        self.duration_ms = (monotonic() - self._started) * 1000
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "server_id": self.server_id,
            "canonical_tool_name": self.canonical_tool_name,
            "original_tool_name": self.original_tool_name,
            "selected_by": self.selected_by,
            "selection_reason": self.selection_reason,
            "policy_decision": self.policy_decision,
            "result_type": self.result_type,
            "is_error": self.is_error,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error_kind": self.error_kind,
        }

