"""Verified resource token and fresh per-tool Authorization admission.

No OAuth signer, private Cedar policy, fallback Permit, or owner API is held
here. Caller-supplied Project/AgentSession/revision are untrusted selectors.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp_types import CallToolRequestParams
from pydantic import BaseModel, ConfigDict
from starlette.requests import Request

from ._resource_claims import decode_verified_bearer
from .infrastructure.decision_reply import decode_allowed

_ISSUER = "https://briareus.koba-nexus.ru/auth/v1/"
_JWKS = "https://briareus.koba-nexus.ru/auth/v1/oidc/certs"
_ALGORITHMS = frozenset({"RS256", "RS384", "RS512", "EdDSA"})
# Match Backend's V2 _resource_scope and _service_identity authority.
# File reads and writes MUST NOT share a fixed Hand-wide action.
_HAND_ACTIONS: dict[str, frozenset[str]] = {
    "files": frozenset({"files.read", "files.write"}),
    "terminal": frozenset({"terminal.execute"}),
    "web": frozenset({"web.access"}),
    "svc": frozenset({"integrations.use", "variables.use"}),
    "reverse": frozenset({"analysis.import"}),
    "infrastructure": frozenset({"integrations.use", "variables.use"}),
}
_RESOURCE_KINDS: dict[str, frozenset[str]] = {
    "files": frozenset({"workspace_path"}),
    "terminal": frozenset({"workspace", "job"}),
    "web": frozenset({"browser_session", "origin"}),
    "svc": frozenset({"repository"}),
    "reverse": frozenset({"analysis_project", "artifact"}),
    "infrastructure": frozenset({"application"}),
}
_TOOL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,127}\Z")
_DIAGNOSTICS = frozenset({"hand_status", "hand_source_summary"})
_MAX_ARGS_BYTES = 1024 * 1024
_OWNER_RESOLVE_TIMEOUT = 3
_DECISION_TIMEOUT = 5
_MAX_DECISION_BYTES = 8192
_MAX_DECISION_REPLY = 4096
# Verified provider issuer/JWKS are canonical deployment facts, not mutable
# operator inputs. Only the per-Hand registered audience and OBSERVED access
# token signing algorithm have independent provisioning lifecycles.
_CONFIG_KEYS = ("MCP_RESOURCE_AUDIENCE", "MCP_RESOURCE_SIGNING_ALGORITHM")


class EffectResourceScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    kind: str
    id: str


class EffectScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    hand: str
    tool: str
    action: str
    resource: EffectResourceScope


@dataclass(frozen=True, slots=True)
class ResourceTrust:
    """Trusted provider metadata; never derived from the incoming JWT."""

    issuer: str
    jwks_uri: str
    audience: str
    signing_algorithm: str

    @classmethod
    def from_environment(
        cls, hand: str, environment: Mapping[str, str] | None = None
    ) -> ResourceTrust | None:
        if hand not in _HAND_ACTIONS:
            raise ValueError("unrecognized MCP Hand")
        config = os.environ if environment is None else environment
        values = [config.get(key, "").strip() for key in _CONFIG_KEYS]
        if not any(values):
            return None
        if not all(values):
            raise ValueError("incomplete MCP resource trust configuration")
        audience, signing_algorithm = values
        expected_audience = f"https://briareus.koba-nexus.ru/hands/{hand}/mcp"
        if (
            audience != expected_audience
            or not 1 <= len(audience) <= 128
            or audience != audience.strip()
            or any(character.isspace() for character in audience)
        ):
            raise ValueError("MCP resource audience is missing or invalid")
        if signing_algorithm not in _ALGORITHMS:
            raise ValueError("unverified MCP access-token signing algorithm")
        return cls(_ISSUER, _JWKS, audience, signing_algorithm)

    def verifier(self) -> JWTVerifier:
        return JWTVerifier(
            issuer=self.issuer,
            jwks_uri=self.jwks_uri,
            audience=self.audience,
            algorithm=self.signing_algorithm,
            ssrf_safe=True,
        )


@dataclass(frozen=True, slots=True)
class ResolvedEffect:
    """Scope from the trusted Hand's actual tool arguments AND resource owner.

    The untrusted MCP caller must never supply this object or its key. A
    registered resolver must consult the real owner/path/session before
    creating one; pure lexical cleanup is not an ownership verification.
    """

    action: str
    kind: str
    resource_id: str
    # The Hand owner supplies canonical executable arguments AFTER resolving
    # the actual resource. The original MCP input must never reach call_next.
    validated_call: CallToolRequestParams | None = None

    def wire_scope(self, hand: str, tool: str) -> EffectScope:
        if not isinstance(tool, str):
            raise ValueError("invalid or unverified Hand effect scope")
        if not isinstance(self.resource_id, str):
            raise ValueError("invalid or unverified Hand effect scope")
        if (
            hand not in _HAND_ACTIONS
            or self.action not in _HAND_ACTIONS[hand]
            or _TOOL_PATTERN.fullmatch(tool) is None
            or self.kind not in _RESOURCE_KINDS[hand]
            or not 1 <= len(self.resource_id) <= 512
            or not unicodedata.is_normalized("NFC", self.resource_id)
            or self.resource_id.strip() != self.resource_id
            or any(ord(char) < 32 or ord(char) == 127 for char in self.resource_id)
        ):
            raise ValueError("invalid or unverified Hand effect scope")
        return EffectScope(
            hand=hand,
            tool=tool,
            action=self.action,
            resource=EffectResourceScope(kind=self.kind, id=self.resource_id),
        )

    def attested_effect_key(self, hand: str, tool: str) -> str:
        """Exact Backend V2 resource-key serialization; NOT a caller header."""
        self.wire_scope(hand, tool)
        return json.dumps(
            [hand, tool, self.kind, self.resource_id], ensure_ascii=True, separators=(",", ":")
        )


# Registered only by trusted Hand construction, NOT client-supplied JSON.
# No resolvers are currently wired until the owner verification contract is real.
EffectResolver = Callable[[CallToolRequestParams], Awaitable[ResolvedEffect]]


@dataclass(frozen=True, slots=True)
class ToolEffectBinding:
    """Immutable trusted tool/action/resource-kind binding.

    The action is fixed by the server's tool definition, NOT chosen by a
    request-time resolver. In particular Files write cannot claim files.read.
    """

    action: str
    kind: str
    resolve: EffectResolver


def _bounded_call(call: CallToolRequestParams) -> CallToolRequestParams:
    """Reject non-JSON/oversized arguments and snapshot mutable input."""
    raw = call.arguments or {}
    if not isinstance(raw, dict):
        raise ValueError("tool arguments must be a JSON object")
    try:
        serialized = json.dumps(
            raw, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
        if len(serialized) > _MAX_ARGS_BYTES:
            raise ValueError("tool arguments exceed MCP request limit")
        normalized = json.loads(serialized)
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("tool arguments are not bounded canonical JSON") from exc
    if not isinstance(normalized, dict):
        raise ValueError("tool arguments must remain an object")
    return call.model_copy(update={"arguments": normalized}, deep=True)


@dataclass(frozen=True, slots=True)
class PrivateDecisionReply:
    """Response received by a real authenticated private transport adapter."""

    status_code: int
    body: bytes


class TrustedPrivateDecisionPort(Protocol):
    """Independent mTLS/Unix peer, body-bound nonce and resource proof owner.

    This port must be constructed by a trusted service supervisor. A caller
    header, Docker DNS, bearer token, or Hand-supplied effect key alone never
    attests the peer. No default implementation or HTTP fallback exists.
    """

    async def decide(
        self,
        *,
        hand: str,
        bearer: str,
        body: bytes,
        resolved_effect_key: str,
    ) -> PrivateDecisionReply: ...


class EffectAuthorizationMiddleware(Middleware):
    """Guard each protected FastMCP tools/call independently, no caching."""

    def __init__(
        self,
        hand: str,
        *,
        effect_bindings: Mapping[str, ToolEffectBinding] | None = None,
        private_decision: TrustedPrivateDecisionPort | None = None,
    ) -> None:
        if hand not in _HAND_ACTIONS:
            raise ValueError("unrecognized MCP Hand")
        self.hand = hand
        self._private_decision = private_decision
        self._bindings = dict(effect_bindings or {})
        for tool, binding in self._bindings.items():
            if not isinstance(tool, str):
                raise ValueError("unsupported registered Hand tool/action/resource kind")
            if not isinstance(binding, ToolEffectBinding):
                raise ValueError("unsupported registered Hand tool/action/resource kind")
            if (
                _TOOL_PATTERN.fullmatch(tool) is None
                or tool in _DIAGNOSTICS
                or tool == "hand_permission_probe"
                or binding.action not in _HAND_ACTIONS[hand]
                or binding.kind not in _RESOURCE_KINDS[hand]
                or not callable(binding.resolve)
            ):
                raise ValueError("unsupported registered Hand tool/action/resource kind")

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        name = context.message.name
        if name in _DIAGNOSTICS:
            return await call_next(context)
        binding = self._bindings.get(name)
        if binding is None:
            if name == "hand_permission_probe":
                raise ToolError("MCP_RESOURCE_SCOPE_UNAVAILABLE")
            raise ToolError("MCP_TOOL_NOT_REGISTERED")
        # Neither a bearer nor an owner resolver may be contacted until a
        # trusted mTLS/Unix decision transport has been injected.
        if self._private_decision is None:
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE")
        # No resource-owner I/O before signed caller verification. Invalid
        # context/arguments, owner failures and timeout all fail closed.
        original_bearer, original_request = self._verified_request()
        # Refuse malformed/ambiguous caller selectors BEFORE even non-effect
        # resource-owner resolution. A valid JWT is not license to probe an
        # owner with a forged Project or revision.
        original_selectors = self._request_selectors(original_request)
        try:
            incoming = _bounded_call(context.message)
            effect = await asyncio.wait_for(
                binding.resolve(incoming), timeout=_OWNER_RESOLVE_TIMEOUT
            )
            if not isinstance(effect, ResolvedEffect):
                raise ValueError("owner resolver returned the wrong action or kind")
            if effect.action != binding.action or effect.kind != binding.kind:
                raise ValueError("owner resolver returned the wrong action or kind")
            scope = effect.wire_scope(self.hand, name)
            # Snapshot the canonical execution arguments before the PDP call:
            # neither mutable client input nor later owner mutations may
            # alter the effect which Cedar actually authorized.
            if not isinstance(effect.validated_call, CallToolRequestParams):
                raise ValueError("owner resolver must provide the validated tool call")
            validated_call = _bounded_call(effect.validated_call)
            if validated_call.name != name:
                raise ValueError("owner resolver changed the tool binding")
        except Exception as exc:
            raise ToolError("MCP_RESOURCE_SCOPE_UNAVAILABLE") from exc
        bearer, current_request = self._verified_request()
        if bearer != original_bearer:
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        if self._request_selectors(current_request) != original_selectors:
            raise ToolError("MCP_CONTEXT_CHANGED")
        await self._check_current_permit(scope=scope, expected_selectors=original_selectors)
        # Owner/PDP awaits cannot renew or replace the original caller.
        # An expired bearer may not begin an effect merely because a
        # decision requested before expiry eventually returned allowed.
        bearer, current_request = self._verified_request()
        if bearer != original_bearer:
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        if self._request_selectors(current_request) != original_selectors:
            raise ToolError("MCP_CONTEXT_CHANGED")
        verified_message = context.message.model_copy(
            update={"arguments": validated_call.arguments}, deep=True
        )
        return await call_next(context.copy(message=verified_message))

    @classmethod
    def _request_selectors(cls, request: Request) -> tuple[UUID, UUID, int]:
        """Canonical untrusted selectors; no owner I/O or claim of authority."""
        try:
            project_uuid = cls._uuid_selector(request.headers.getlist("x-briareus-project-uuid"))
            session_uuid = cls._uuid_selector(
                request.headers.getlist("x-briareus-agent-session-uuid")
            )
            revisions = request.headers.getlist("x-briareus-grant-revision")
            if len(revisions) != 1 or not revisions[0].isascii() or not revisions[0].isdecimal():
                raise ValueError("missing or invalid revision")
            revision = int(revisions[0])
            if not 1 <= revision <= 2**63 - 1 or str(revision) != revisions[0]:
                raise ValueError("revision outside canonical range")
        except (ValueError, OverflowError) as exc:
            raise ToolError("MCP_CONTEXT_INVALID") from exc
        return project_uuid, session_uuid, revision

    async def _check_current_permit(
        self, *, scope: EffectScope, expected_selectors: tuple[UUID, UUID, int]
    ) -> None:
        bearer, request = self._verified_request()
        selectors = self._request_selectors(request)
        if selectors != expected_selectors:
            raise ToolError("MCP_CONTEXT_CHANGED")
        project_uuid, session_uuid, revision = selectors
        body = {
            "project_uuid": str(project_uuid),
            "agent_session_uuid": str(session_uuid),
            "action": scope.action,
            "expected_grant_revision": revision,
            "hand": scope.hand,
            "tool": scope.tool,
            "resource": scope.resource.model_dump(mode="json"),
        }
        # Body bytes and exact effect key are inputs to the Backend V2
        # transport attestor. Only an independently authenticated adapter
        # may establish peer identity, nonce freshness or resource ownership.
        private = self._private_decision
        if private is None:
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE")
        try:
            wire = json.dumps(
                body, ensure_ascii=True, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
            if not 0 < len(wire) <= _MAX_DECISION_BYTES:
                raise ValueError("oversized private decision")
            resource = scope.resource
            effect_key = json.dumps(
                [self.hand, scope.tool, resource.kind, resource.id],
                ensure_ascii=True,
                separators=(",", ":"),
            )
            reply = await asyncio.wait_for(
                private.decide(
                    hand=self.hand,
                    bearer=bearer,
                    body=wire,
                    resolved_effect_key=effect_key,
                ),
                timeout=_DECISION_TIMEOUT,
            )
        except Exception as exc:
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE") from exc
        if not isinstance(reply, PrivateDecisionReply):
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE")
        if reply.status_code == 401:
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        if reply.status_code == 403:
            raise ToolError("MCP_ACCESS_DENIED")
        if not isinstance(reply.body, bytes):
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE")
        if reply.status_code != 200 or len(reply.body) > _MAX_DECISION_REPLY:
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE")
        try:
            decode_allowed(reply.body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ToolError("MCP_AUTHORIZATION_UNAVAILABLE") from exc

    @staticmethod
    def _verified_request() -> tuple[str, Request]:
        """Require SDK-verified resource JWT before any resource-owner I/O."""
        try:
            verified = get_access_token()
        except RuntimeError as exc:
            raise ToolError("MCP_IDENTITY_UNVERIFIED") from exc
        if verified is None or not verified.token:
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        claims = verified.claims
        if not isinstance(claims, dict):
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        if decode_verified_bearer(claims) is None:
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        try:
            # Starlette Request.headers caches a Headers wrapper; async owner
            # code may mutate the underlying ASGI scope before our final
            # continuity check. Reconstruct a fresh read-only Request view
            # from the CURRENT raw scope rather than reusing cached headers.
            request = Request(get_http_request().scope)
        except (RuntimeError, ValueError, TypeError) as exc:
            raise ToolError("MCP_HTTP_CONTEXT_REQUIRED") from exc
        bearer = request.headers.getlist("authorization")
        if (
            len(bearer) != 1
            or bearer[0] != f"Bearer {verified.token}"
            or request.headers.getlist("cookie")
        ):
            raise ToolError("MCP_IDENTITY_UNVERIFIED")
        return bearer[0], request

    @staticmethod
    def _uuid_selector(values: list[str]) -> UUID:
        if len(values) != 1 or not 1 <= len(values[0]) <= 64:
            raise ValueError("exactly one UUID required")
        result = UUID(values[0])
        if result.version != 4 or str(result) != values[0]:
            raise ValueError("canonical UUIDv4 required")
        return result
