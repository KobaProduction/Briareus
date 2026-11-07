"""Deployment-only node registration; never imported by application runtimes."""

from ._cli import main
from ._models import (
    ErrorCode,
    NodeRegistrationError,
    NodeResult,
    NodeSpec,
    RegistryConfig,
    RoleRegistry,
)
from ._service import ensure_node
from ._zitadel import ZitadelRoleRegistry

__all__ = [
    "ErrorCode",
    "NodeRegistrationError",
    "NodeResult",
    "NodeSpec",
    "RegistryConfig",
    "RoleRegistry",
    "ZitadelRoleRegistry",
    "ensure_node",
    "main",
]
