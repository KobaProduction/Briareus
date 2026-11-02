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
from project_runtime_client.domain.resource_scope import ResourceOrigin as ResourceOrigin
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
