"""Compatibility exports for the shared project runtime client implementation."""

from typing import Protocol as Protocol

from project_runtime_client.application.resource_authority import (
    ResourceAuthorityPort as ResourceAuthorityPort,
)
from project_runtime_client.domain.authorization import ProjectAction as ProjectAction
from project_runtime_client.domain.authorization import ProjectInvocation as ProjectInvocation
from project_runtime_client.domain.authorization import ProjectPermit as ProjectPermit
