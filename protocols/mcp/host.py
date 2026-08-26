"""The smallest useful Hi-Agent MCP Host composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from context.models import ContextBudget
from context.tool_selector import MCPToolSelector, ToolSelection
from runtime.trace import MCPTrace
from tools.registry import MyToolRegistry

from .adapter import MCPToolAdapter
from .catalog import MCPToolCatalog
from .manager import MCPManager, MCPServerConfig
from .policy import MCPPolicy, MCPPolicyDenied


@dataclass(slots=True)
class MCPExecution:
    result: str
    trace: MCPTrace


class MCPHost:
    """Coordinates discovery, selection, policy, registry, execution and trace."""

    def __init__(
        self,
        *,
        policy: MCPPolicy | None = None,
        registry: MyToolRegistry | None = None,
    ) -> None:
        self.policy = policy or MCPPolicy()
        self.registry = registry or MyToolRegistry()
        self.catalog = MCPToolCatalog()
        self.selector = MCPToolSelector()
        self.managers: dict[str, MCPManager] = {}
        self.last_traces: list[MCPTrace] = []

    def add_server(self, config: MCPServerConfig) -> list:
        manager = MCPManager(config)
        self.managers[config.server_id] = manager
        entries = self.catalog.refresh(manager)
        for entry in entries:
            self.registry.register_tool(MCPToolAdapter(manager, entry))
        return entries

    def refresh_server(self, server_id: str) -> list:
        manager = self.managers[server_id]
        old_names = {
            entry.canonical_tool_name
            for entry in self.catalog.entries()
            if entry.server_id == server_id
        }
        entries = self.catalog.refresh(manager)
        for name in old_names:
            self.registry.unregister(name)
        for entry in entries:
            self.registry.register_tool(MCPToolAdapter(manager, entry))
        return entries

    def select_tools(
        self,
        query: str,
        *,
        budget: ContextBudget | None = None,
    ) -> ToolSelection:
        return self.selector.select(
            query,
            self.catalog.entries(),
            budget=budget,
        )

    def execute(
        self,
        canonical_tool_name: str,
        arguments: dict[str, Any],
        *,
        selected_by: str = "explicit",
        selection_reason: str = "",
        confirmed: bool = False,
    ) -> MCPExecution:
        entry = self.catalog.get(canonical_tool_name)
        trace = MCPTrace(
            server_id=entry.server_id,
            canonical_tool_name=entry.canonical_tool_name,
            original_tool_name=entry.original_tool_name,
            selected_by=selected_by,
            selection_reason=selection_reason,
        )
        decision = self.policy.check(entry, confirmed=confirmed)
        trace.policy_decision = (
            "allow" if decision.allowed else f"deny:{decision.reason}"
        )
        if not decision.allowed:
            trace.finish(
                status="policy_denied",
                error_kind="policy_denied",
            )
            self.last_traces.append(trace)
            raise MCPPolicyDenied(decision.reason)

        adapter = self.registry.get_tools(canonical_tool_name)
        if adapter is None or not isinstance(adapter, MCPToolAdapter):
            trace.finish(status="adapter_error", error_kind="adapter_error")
            self.last_traces.append(trace)
            raise RuntimeError(
                f"MCP adapter missing for {canonical_tool_name}"
            )

        try:
            call_result = adapter.call_result(arguments)
            result = adapter.render_result(call_result)
            status = "tool_error" if call_result.is_error else "completed"
            trace.finish(
                status=status,
                result_type=call_result.result_type,
                is_error=call_result.is_error,
                error_kind="tool_error" if call_result.is_error else None,
            )
            self.last_traces.append(trace)
            return MCPExecution(result=result, trace=trace)
        except Exception:
            trace.finish(status="transport_error", error_kind="transport_error")
            self.last_traces.append(trace)
            raise
