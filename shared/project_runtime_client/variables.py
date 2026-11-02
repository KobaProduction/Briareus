"""Compatibility imports for resource metadata and application selectors."""

from .application.variables import (
    ProjectVariablePort,
    ProjectVariableSelector,
)
from .domain.resources import (
    ProjectVariableError,
    ProjectVariableRef,
    VariableKind,
)

__all__ = [
    "ProjectVariableError",
    "ProjectVariablePort",
    "ProjectVariableRef",
    "ProjectVariableSelector",
    "VariableKind",
]
