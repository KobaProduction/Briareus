"""Environment-driven role preparation owned by Control Panel API startup."""

from ._models import ErrorCode, NodeRegistrationError, NodeSpec, RegistryConfig
from ._startup import NodeProvisioningSettings, ensure_node_role
from ._zitadel import ZitadelRoleRegistry

__all__ = [
    "ErrorCode",
    "NodeProvisioningSettings",
    "NodeRegistrationError",
    "NodeSpec",
    "RegistryConfig",
    "ZitadelRoleRegistry",
    "ensure_node_role",
]
