"""Compatibility exports for the shared project runtime client implementation."""

from project_runtime_client.application.variables import ProjectVariablePort as ProjectVariablePort
from project_runtime_client.application.variables import (
    ProjectVariableSelector as ProjectVariableSelector,
)
from project_runtime_client.domain.resources import ProjectVariableError as ProjectVariableError
from project_runtime_client.domain.resources import ProjectVariableRef as ProjectVariableRef
from project_runtime_client.domain.resources import VariableKind as VariableKind
from project_runtime_client.variables import __all__ as __all__
