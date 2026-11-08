"""Private-network service registration and live discovery without a Docker socket."""

from ._discovery import ServiceDiscovery
from ._models import DiscoveredService, DiscoverySnapshot
from ._registration import attach_service_discovery
from ._registry import ServiceRegistry

__all__ = [
    "DiscoveredService",
    "DiscoverySnapshot",
    "ServiceDiscovery",
    "ServiceRegistry",
    "attach_service_discovery",
]
