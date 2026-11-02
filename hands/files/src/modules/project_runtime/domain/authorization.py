"""Compatibility exports for the shared project runtime client implementation."""

from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from typing import Literal as Literal
from uuid import UUID as UUID

from project_runtime_client.domain.authorization import ProjectAccessDenied as ProjectAccessDenied
from project_runtime_client.domain.authorization import ProjectAction as ProjectAction
from project_runtime_client.domain.authorization import ProjectInvocation as ProjectInvocation
from project_runtime_client.domain.authorization import (
    ProjectOperationScope as ProjectOperationScope,
)
from project_runtime_client.domain.authorization import ProjectOwnerFence as ProjectOwnerFence
from project_runtime_client.domain.authorization import ProjectPermit as ProjectPermit
from project_runtime_client.domain.identifiers import valid_uuid as valid_uuid
from project_runtime_client.domain.revisions import valid_project_revision as valid_project_revision
