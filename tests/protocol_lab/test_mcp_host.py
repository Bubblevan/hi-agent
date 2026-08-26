from __future__ import annotations

import pytest
from mcp.server import MCPServer

from context.models import ContextBudget
from protocols.mcp.host import MCPHost
from protocols.mcp.host.manager import MCPServerConfig, MCPManager
from protocols.mcp.host.policy import MCPPolicy, MCPPolicyDenied


def make_server():
    server = MCPServer(name="local-files", version="1.0.0")

    def read_file(path: str) -> dict:
        return {"path": path, "text": "protocol notes"}

    def grep_code(query: str) -> list[str]:
        return [f"protocols/mcp/mini_mcp/{query}.py"]

    def delete_file(path: str) -> str:
        return f"deleted {path}"

    def fail_tool() -> str:
        raise RuntimeError("simulated server failure")

    server.tool()(read_file)
    server.tool()(grep_code)
    server.tool()(delete_file)
    server.tool()(fail_tool)
    return server


def make_host() -> MCPHost:
    host = MCPHost(policy=MCPPolicy())
    host.add_server(
        MCPServerConfig(
            server_id="filesystem",
            source=make_server(),
        )
    )
    return host


def test_manager_discovers_and_catalogs_official_sdk_server():
    host = make_host()

    assert [entry.canonical_tool_name for entry in host.catalog.entries()] == [
        "filesystem.delete_file",
        "filesystem.fail_tool",
        "filesystem.grep_code",
        "filesystem.read_file",
    ]
    assert host.catalog.get("filesystem.grep_code").server_name == "local-files"


def test_refresh_rebuilds_catalog_and_registry_for_one_server():
    host = make_host()
    assert "filesystem.grep_code" in host.registry.list_tools()

    host.refresh_server("filesystem")

    assert "filesystem.grep_code" in host.registry.list_tools()
    assert len(host.catalog) == 4


def test_selector_uses_existing_context_budget_and_excludes_unrelated_tool():
    host = make_host()

    selection = host.select_tools(
        "搜索项目中所有 Mini-MCP 相关代码",
        budget=ContextBudget(
            soft_limit=100,
            hard_limit=200,
            output_reserve=20,
        ),
    )

    names = {entry.canonical_tool_name for entry in selection.selected}
    assert "filesystem.grep_code" in names
    assert "filesystem.delete_file" not in names
    assert selection.reasons["filesystem.delete_file"] == "no query overlap"


def test_host_executes_read_only_tool_and_records_trace():
    host = make_host()

    execution = host.execute(
        "filesystem.grep_code",
        {"query": "protocol"},
        selected_by="context_selector",
        selection_reason="lexical overlap score=1",
    )

    assert "protocols/mcp/mini_mcp/protocol.py" in execution.result
    assert execution.trace.status == "completed"
    assert execution.trace.policy_decision == "allow"
    assert execution.trace.result_type == "complete"
    assert execution.trace.is_error is False


def test_policy_denied_write_does_not_call_tool():
    host = make_host()

    try:
        host.execute("filesystem.delete_file", {"path": "x"})
    except MCPPolicyDenied as exc:
        assert "dangerous" in str(exc)
    else:
        raise AssertionError("write tool should have been denied")

    assert host.last_traces[-1].status == "policy_denied"


def test_host_preserves_server_tool_error_as_tool_error_trace():
    host = make_host()

    execution = host.execute("filesystem.fail_tool", {})

    assert execution.trace.status == "tool_error"
    assert execution.trace.error_kind == "tool_error"
    assert "MCP tool error" in execution.result


def test_manager_surfaces_connection_failure():
    manager = MCPManager(
        MCPServerConfig(
            server_id="broken",
            source=object(),
        )
    )

    with pytest.raises(Exception):
        manager.list_tools()
