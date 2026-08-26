"""Hi-Agent's MCP Host integration layer.

The official MCP SDK owns wire protocol details.  This package owns the
application boundary: catalog, adapter, policy, selection, and trace.
"""

from .adapter import MCPToolAdapter
from .catalog import MCPToolCatalog, MCPToolEntry
from .manager import MCPCallResult, MCPManager, MCPServerConfig
from .policy import MCPPolicy, MCPPolicyDenied, RiskLevel
from .host import MCPExecution, MCPHost

__all__ = [
    "MCPCallResult",
    "MCPExecution",
    "MCPHost",
    "MCPManager",
    "MCPPolicy",
    "MCPPolicyDenied",
    "MCPServerConfig",
    "MCPToolAdapter",
    "MCPToolCatalog",
    "MCPToolEntry",
    "RiskLevel",
]
