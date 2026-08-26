"""Pre-call policy for externally discovered MCP tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .catalog import MCPToolEntry


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    WRITE = "write"
    DANGEROUS = "dangerous"


class MCPPolicyDenied(PermissionError):
    """Raised when a tool is rejected before an MCP request is sent."""


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    risk: RiskLevel
    reason: str
    requires_confirmation: bool = False


class MCPPolicy:
    """Conservative default policy.

    The caller may explicitly allow writes. Dangerous operations remain
    denied unless a future policy implementation adds an explicit capability.
    """

    def __init__(self, *, allow_writes: bool = False) -> None:
        self.allow_writes = allow_writes

    def check(
        self,
        entry: MCPToolEntry,
        *,
        confirmed: bool = False,
    ) -> PolicyDecision:
        try:
            risk = RiskLevel(entry.risk)
        except ValueError:
            risk = RiskLevel.DANGEROUS

        if risk is RiskLevel.READ_ONLY:
            return PolicyDecision(True, risk, "read-only tool")
        if risk is RiskLevel.WRITE:
            if self.allow_writes and confirmed:
                return PolicyDecision(True, risk, "write explicitly confirmed")
            return PolicyDecision(
                False,
                risk,
                "write tool requires explicit confirmation",
                requires_confirmation=True,
            )
        return PolicyDecision(False, risk, "dangerous tool denied by default")

