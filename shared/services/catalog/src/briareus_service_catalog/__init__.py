"""Provider identity and public MCP paths, shared by runtime and deployment consumers."""

from ._models import BUILTIN_SERVICES, ServiceDefinition, service_definition

__all__ = ["BUILTIN_SERVICES", "ServiceDefinition", "service_definition"]
