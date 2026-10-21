"""Wire contracts shared by Core, Node Agent and node Gateway.

These describe placement, never identity or permission. Rauthy and Cedar remain
authoritative; knowing a node/module UUID does not authorize an MCP call.
"""

from .models import (
    Deployment, ModuleRelease, NodeBudget, NodeRecord, NodeScope, ResourceLimits, WorkspaceMount,
)

__all__ = [
    "Deployment", "ModuleRelease", "NodeBudget", "NodeRecord", "NodeScope", "ResourceLimits", "WorkspaceMount",
]
