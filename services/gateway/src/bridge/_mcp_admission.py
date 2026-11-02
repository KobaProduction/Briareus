"""Coarse MCP connection admission against independent Authorization.

Incoming selectors are not identity proof. Only an independently attested
Authorization 200 with the exact Permit body may allow Gateway forwarding.
"""

from __future__ import annotations

from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse

from node_protocol._mcp_rejection import _McpRejection

from .application.admission import AuthorizeConnection
from .domain.admission import (
    ConnectionAdmission,
    ConnectionDecision,
    HumanAdmission,
    McpAdmission,
    connection_selectors,
)
from .infrastructure.admission import (
    PrivateConnectionDecisions,
    TrustedGatewayDecisionPort,
)
from .single_origin import MCP_MODULES

_HAND_TARGETS: dict[str, str] = {name: f"http://briareus-{name}:8000/mcp" for name in MCP_MODULES}
_DECISION_TIMEOUT_SECONDS = 5


class McpAdmissionRejected(_McpRejection):
    """A bounded public transport rejection, never a Cedar decision."""


def connection_target(admission: McpAdmission) -> str:
    return _HAND_TARGETS[admission.hand]


def admission_error(code: str, status: int) -> JSONResponse:
    return JSONResponse(
        {"code": code},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _single_header(request: Request, name: str) -> str:
    values = request.headers.getlist(name)
    if len(values) != 1 or not values[0] or len(values[0]) > 128 or values[0].strip() != values[0]:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    return values[0]


def _human_web_carrier(
    request: Request, hand: str, bearer: str, values: list[str]
) -> HumanAdmission:
    if (
        hand not in {"web", "files", "terminal", "reverse"}
        or len(values) != 1
        or not 0 < len(values[0]) <= 8192
        or request.headers.getlist("x-briareus-agent-session-uuid")
        or request.headers.getlist("x-briareus-grant-revision")
    ):
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    project = _single_header(request, "x-briareus-project-uuid")
    try:
        project_uuid = UUID(project)
        if project_uuid.version != 4 or str(project_uuid) != project:
            raise ValueError("Canonical project required")
    except ValueError as exc:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400) from exc
    return HumanAdmission(bearer, project_uuid, values[0], hand)


def parse_connection_admission(request: Request) -> McpAdmission:
    """Parse strictly bounded, *untrusted* selectors for the real PDP."""
    hand = request.url.path.removeprefix("/hands/").removesuffix("/mcp")
    canonical = f"/hands/{hand}/mcp"
    if (
        hand not in _HAND_TARGETS
        or request.url.path != canonical
        or request.scope.get("raw_path") != canonical.encode("ascii")
    ):
        # A path normalized from percent-encoding, dot segments or duplicate
        # separators is NOT the exact public MCP resource URI. Reject it
        # before consulting Authorization or passing a bearer to a Hand.
        raise McpAdmissionRejected("MCP_MODULE_UNKNOWN", 404)
    if request.scope.get("query_string", b"") != b"":
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400)
    if request.method != "POST":
        raise McpAdmissionRejected("MCP_METHOD_UNSUPPORTED", 405)
    if request.headers.getlist("cookie"):
        raise McpAdmissionRejected("MCP_COOKIE_NOT_ALLOWED", 400)
    authorizations = request.headers.getlist("authorization")
    if len(authorizations) != 1:
        raise McpAdmissionRejected("MCP_BEARER_REQUIRED", 401)
    bearer = authorizations[0]
    if (
        not bearer.startswith("Bearer ")
        or len(bearer) > 8192
        or bearer.count(" ") != 1
        or not bearer[7:]
        or any(char.isspace() for char in bearer[7:])
    ):
        raise McpAdmissionRejected("MCP_BEARER_REQUIRED", 401)
    human = request.headers.getlist("x-briareus-human-permit") + request.headers.getlist(
        "x-briareus-human-web-permit"
    )
    if human:
        return _human_web_carrier(request, hand, bearer, human)
    try:
        selectors = connection_selectors(
            _single_header(request, "x-briareus-project-uuid"),
            _single_header(request, "x-briareus-agent-session-uuid"),
            _single_header(request, "x-briareus-grant-revision"),
        )
    except (ValueError, OverflowError) as exc:
        raise McpAdmissionRejected("MCP_CONTEXT_INVALID", 400) from exc
    return ConnectionAdmission(
        hand, bearer, selectors.project_uuid, selectors.agent_session_uuid, selectors.grant_revision
    )


async def authorize_connection(
    private: TrustedGatewayDecisionPort | None, admission: ConnectionAdmission
) -> JSONResponse | None:
    """Only a real authenticated private peer may carry Bearer to Authorization."""
    decisions = PrivateConnectionDecisions(private) if private is not None else None
    decision = await AuthorizeConnection(decisions, _DECISION_TIMEOUT_SECONDS).execute(admission)
    if decision is ConnectionDecision.IDENTITY_UNVERIFIED:
        return admission_error("MCP_IDENTITY_UNVERIFIED", 401)
    if decision is ConnectionDecision.ACCESS_DENIED:
        return admission_error("MCP_ACCESS_DENIED", 403)
    if decision is not ConnectionDecision.PERMIT:
        return admission_error("MCP_AUTHORIZATION_UNAVAILABLE", 503)
    return None
