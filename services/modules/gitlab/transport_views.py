"""Compatibility exports for the shared GitLab technical implementation."""

from collections.abc import Mapping as Mapping
from dataclasses import dataclass as dataclass
from dataclasses import field as field

from source_control.providers.gitlab.transport_views import (
    GitLabAcknowledgement as GitLabAcknowledgement,
)
from source_control.providers.gitlab.transport_views import (
    GitLabModelResponse as GitLabModelResponse,
)
from source_control.providers.gitlab.transport_views import GitLabPagination as GitLabPagination
from source_control.providers.gitlab.transport_views import (
    GitLabRequestHeaders as GitLabRequestHeaders,
)
from source_control.providers.gitlab.transport_views import _header_integer as _header_integer
