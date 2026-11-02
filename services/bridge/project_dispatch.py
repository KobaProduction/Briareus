"""Compatibility imports for the unmounted legacy private dispatch entrypoint."""

from uuid import UUID

from fastmcp.tools import ToolResult
from mcp.types import CallToolRequestParams, CallToolResult
from pydantic import TypeAdapter

from modules.project_runtime import ProjectInvocation

from .application.owner_readiness import (
    ProjectOwnerReadinessPort as ProjectOwnerReadinessPort,
)
from .application.owner_readiness import (
    ProjectOwnerReleaseManifestPort as ProjectOwnerReleaseManifestPort,
)
from .application.project_contracts import FileWriteObservation, ProjectResult
from .application.project_dispatch import (
    _MUTATING_ACTIONS as _MUTATING_ACTIONS,
)
from .application.project_dispatch import (
    _PRIVATE_TOOL_ACTIONS as _PRIVATE_TOOL_ACTIONS,
)
from .application.project_dispatch import (
    AuthenticatedProjectForwarder as AuthenticatedProjectForwarder,
)
from .application.project_dispatch import (
    AuthorizedToolForward as AuthorizedToolForward,
)
from .application.project_dispatch import (
    ProjectGatewayDispatch as ProjectGatewayDispatch,
)
from .application.project_dispatch import (
    ProjectToolClassifier as ProjectToolClassifier,
)
from .domain.project_dispatch import (
    ExpectedOwnerSchema as ExpectedOwnerSchema,
)
from .domain.project_dispatch import (
    OwnerServiceName as OwnerServiceName,
)
from .domain.project_dispatch import (
    ProjectGatewayDispatchUnavailable as ProjectGatewayDispatchUnavailable,
)
from .domain.project_dispatch import (
    VerifiedOwnerReadiness as VerifiedOwnerReadiness,
)
from .infrastructure.project_codec import normalize_command

_RESULT: TypeAdapter[ProjectResult] = TypeAdapter(ProjectResult)


async def dispatch_mcp_request(
    dispatcher: ProjectGatewayDispatch,
    invocation: ProjectInvocation,
    *,
    backend: str,
    request: CallToolRequestParams,
    request_uuid: UUID | None = None,
) -> CallToolResult:
    """Adapt the private SDK request; this function is never publicly mounted."""
    command = normalize_command(backend, request)
    result = await dispatcher.dispatch(
        invocation,
        backend=backend,
        tool=request.name,
        arguments=command,
        request_uuid=request_uuid,
    )
    # The concrete command/result union owns serialization, including UUIDs and
    # datetimes. Native JSON never becomes a use-case contract.
    fields = _RESULT.dump_python(result, mode="json")
    if isinstance(result, FileWriteObservation):
        fields["expires_at"] = result.expires_at.isoformat()
    converted = ToolResult(content=fields, structured_content=fields)
    return CallToolResult(
        content=converted.content, structured_content=converted.structured_content
    )
