"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from typing import Literal as Literal
from uuid import UUID as UUID

from project_runtime_client.domain.identifiers import valid_uuid as valid_uuid
from project_runtime_client.domain.resource_scope import (
    EffectiveResourceScope as EffectiveResourceScope,
)
from project_runtime_client.domain.resource_scope import (
    ProjectResourceScopeError as ProjectResourceScopeError,
)
from project_runtime_client.domain.resources import IntegrationAction as IntegrationAction
from project_runtime_client.domain.resources import IntegrationOperation as IntegrationOperation
from project_runtime_client.domain.resources import IntegrationProvider as IntegrationProvider
from project_runtime_client.domain.resources import (
    ProjectIntegrationError as ProjectIntegrationError,
)
from project_runtime_client.domain.resources import ProjectIntegrationRef as ProjectIntegrationRef
from project_runtime_client.domain.resources import ProjectVariableError as ProjectVariableError
from project_runtime_client.domain.resources import ProjectVariableRef as ProjectVariableRef
from project_runtime_client.domain.resources import VariableKind as VariableKind
from project_runtime_client.domain.resources import integration_action as integration_action
