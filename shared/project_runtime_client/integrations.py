"""Compatibility imports for resource metadata and application selectors."""

from .application.integrations import (
    ProjectIntegrationPort,
    ProjectIntegrationSelector,
)
from .domain.resources import (
    IntegrationOperation,
    IntegrationProvider,
    ProjectIntegrationError,
    ProjectIntegrationRef,
)

__all__ = [
    "IntegrationOperation",
    "IntegrationProvider",
    "ProjectIntegrationError",
    "ProjectIntegrationPort",
    "ProjectIntegrationRef",
    "ProjectIntegrationSelector",
]
