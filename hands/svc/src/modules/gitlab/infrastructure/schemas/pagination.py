"""Compatibility exports for the shared GitLab technical implementation."""

from pydantic import BaseModel as BaseModel

from source_control.providers.gitlab.infrastructure.schemas.pagination import (
    PageQuery as PageQuery,
)
