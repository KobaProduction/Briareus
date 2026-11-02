"""Compatibility exports for the shared project runtime client implementation."""

from project_runtime_client.application.integrations import (
    ProjectIntegrationPort as ProjectIntegrationPort,
)
from project_runtime_client.application.integrations import (
    ProjectIntegrationSelector as ProjectIntegrationSelector,
)
from project_runtime_client.domain.resources import IntegrationOperation as IntegrationOperation
from project_runtime_client.domain.resources import IntegrationProvider as IntegrationProvider
from project_runtime_client.domain.resources import (
    ProjectIntegrationError as ProjectIntegrationError,
)
from project_runtime_client.domain.resources import ProjectIntegrationRef as ProjectIntegrationRef
from project_runtime_client.integrations import __all__ as __all__
