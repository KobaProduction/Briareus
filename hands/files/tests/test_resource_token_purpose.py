"""Real SDK signature checks with ephemeral tokens; no deployed identity/grant."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp_types import CallToolRequestParams
from pydantic import JsonValue
from starlette.requests import Request

from hand_runtime._effect_auth import (
    EffectAuthorizationMiddleware,
    PrivateDecisionReply,
    ResolvedEffect,
    ToolEffectBinding,
)
from hand_runtime._resource_claims import decode_verified_bearer


@dataclass(slots=True)
class ActiveCaller:
    verified: AccessToken | None
    bearer: str


class UnexpectedDecision:
    async def decide(
        self, *, hand: str, bearer: str, body: bytes, resolved_effect_key: str
    ) -> PrivateDecisionReply:
        del hand, bearer, body, resolved_effect_key
        raise AssertionError("invalid identity or unresolved scope reached the PDP")


async def main() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    issuer = "https://briareus.koba-nexus.ru/auth/v1/"
    audience = "https://briareus.koba-nexus.ru/hands/files/mcp"
    verifier = JWTVerifier(public_key=public, issuer=issuer, audience=audience, algorithm="RS256")
    now = int(time.time())
    base: dict[str, JsonValue] = {
        "iss": issuer,
        "aud": ["fixture-client", audience],
        "sub": "fixture-subject",
        "iat": now,
        "nbf": now,
        "exp": now + 60,
        "azp": "fixture-client",
        "jti": "fixture-token-id",
        "typ": "Bearer",
    }
    visits: list[CallToolRequestParams] = []

    async def resolver(arguments: CallToolRequestParams) -> ResolvedEffect:
        visits.append(arguments)
        raise ValueError("no actual resource owner configured")

    async def effect(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        del context
        raise AssertionError("no business effect authorized in this test")

    middleware = EffectAuthorizationMiddleware(
        "files",
        effect_bindings={"read_file": ToolEffectBinding("files.read", "workspace_path", resolver)},
        private_decision=UnexpectedDecision(),
    )
    for update in (
        {},
        {"typ": "Id"},
        {"typ": "Refresh"},
        {"typ": None},
        {"cnf": {"jkt": "unsupported"}},
        {"act": {"sub": "delegated-untrusted"}},
        {"exp": now + 86401},
        {"jti": "contains space"},
        {"azp": ""},
        {"aud": [audience, audience]},
    ):
        claims = base | update
        token = jwt.encode(claims, key, algorithm="RS256")
        verified = await verifier.verify_token(token)
        if verified is None:
            assert update  # SDK may itself reject some malformed inputs.
            continue
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [
                    (b"authorization", ("Bearer " + token).encode()),
                    (b"x-briareus-project-uuid", b"11111111-1111-4111-8111-111111111111"),
                    (b"x-briareus-agent-session-uuid", b"22222222-2222-4222-8222-222222222222"),
                    (b"x-briareus-grant-revision", b"1"),
                ],
            }
        )
        before = len(visits)
        context = MiddlewareContext(
            message=CallToolRequestParams(name="read_file", arguments={"path": "file"})
        )
        with (
            patch("hand_runtime._effect_auth.get_access_token", return_value=verified),
            patch("hand_runtime._effect_auth.get_http_request", return_value=request),
        ):
            try:
                await middleware.on_call_tool(context, effect)
            except ToolError as exc:
                expected = "MCP_IDENTITY_UNVERIFIED" if update else "MCP_RESOURCE_SCOPE_UNAVAILABLE"
                assert str(exc) == expected, (update.keys(), str(exc))
            else:
                raise AssertionError("effect executed without actual authority")
        assert len(visits) == before + (0 if update else 1)

    # Even a valid SDK-verified actor must not contact an owner with
    # noncanonical Project/AgentSession/revision selectors.
    original_token = jwt.encode(base, key, algorithm="RS256")
    original_verified = await verifier.verify_token(original_token)
    assert original_verified is not None
    for bad_name, bad_value in (
        (b"x-briareus-project-uuid", b"11111111-1111-4111-8111-11111111111A"),
        (b"x-briareus-agent-session-uuid", b"22222222-2222-4222-8222-22222222222A"),
        (b"x-briareus-grant-revision", b"01"),
        (b"x-briareus-grant-revision", b" 1"),
    ):
        headers = [
            (b"authorization", ("Bearer " + original_token).encode()),
            (b"x-briareus-project-uuid", b"11111111-1111-4111-8111-111111111111"),
            (b"x-briareus-agent-session-uuid", b"22222222-2222-4222-8222-222222222222"),
            (b"x-briareus-grant-revision", b"1"),
        ]
        malformed = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/mcp",
                "headers": [
                    (name, bad_value if name == bad_name else value) for name, value in headers
                ],
            }
        )
        before = len(visits)
        with (
            patch("hand_runtime._effect_auth.get_access_token", return_value=original_verified),
            patch("hand_runtime._effect_auth.get_http_request", return_value=malformed),
        ):
            try:
                await middleware.on_call_tool(
                    MiddlewareContext(
                        message=CallToolRequestParams(name="read_file", arguments={"path": "file"})
                    ),
                    effect,
                )
            except ToolError as exc:
                assert str(exc) == "MCP_CONTEXT_INVALID", (bad_name, str(exc))
            else:
                raise AssertionError("malformed resource selector reached owner resolver")
        assert len(visits) == before, bad_name

    # A synthetic positive reply is used only to exercise the waiting
    # boundary. It is never sent to a running Hand or used to read a file.
    async def scoped_resolver(arguments: CallToolRequestParams) -> ResolvedEffect:
        return ResolvedEffect("files.read", "workspace_path", "fixture-file", arguments)

    async def decision_case(mode: str) -> None:
        raw = jwt.encode(base, key, algorithm="RS256")
        original = await verifier.verify_token(raw)
        alternate_raw = jwt.encode(base | {"sub": "other-fixture-subject"}, key, algorithm="RS256")
        alternate = await verifier.verify_token(alternate_raw)
        active = ActiveCaller(original, raw)
        clock = [float(now)]
        revision = [b"1"]
        calls: list[str] = []

        class PendingDecision:
            async def decide(
                self, *, hand: str, bearer: str, body: bytes, resolved_effect_key: str
            ) -> PrivateDecisionReply:
                del hand, bearer, body, resolved_effect_key
                if mode == "expired_during_reply":
                    clock[0] = now + 61
                elif mode == "rebound_during_reply":
                    active.verified = alternate
                    active.bearer = alternate_raw
                elif mode == "rebound_revision_during_reply":
                    revision[0] = b"2"
                return PrivateDecisionReply(200, b'{"allowed":true}')

        fixture_result = ToolResult(content="fixture")

        async def fixture_only_effect(
            context: MiddlewareContext[CallToolRequestParams],
        ) -> ToolResult:
            assert context.message.name == "read_file"
            calls.append("fixture_only_no_file_access")
            return fixture_result

        def current_request() -> Request:
            return Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/mcp",
                    "headers": [
                        (b"authorization", ("Bearer " + active.bearer).encode()),
                        (b"x-briareus-project-uuid", b"11111111-1111-4111-8111-111111111111"),
                        (b"x-briareus-agent-session-uuid", b"22222222-2222-4222-8222-222222222222"),
                        (b"x-briareus-grant-revision", revision[0]),
                    ],
                }
            )

        gate = EffectAuthorizationMiddleware(
            "files",
            effect_bindings={
                "read_file": ToolEffectBinding("files.read", "workspace_path", scoped_resolver)
            },
            private_decision=PendingDecision(),
        )
        with (
            patch("hand_runtime._resource_claims.time.time", side_effect=lambda: clock[0]),
            patch(
                "hand_runtime._effect_auth.get_access_token", side_effect=lambda: active.verified
            ),
            patch("hand_runtime._effect_auth.get_http_request", side_effect=current_request),
        ):
            try:
                result = await gate.on_call_tool(
                    MiddlewareContext(
                        message=CallToolRequestParams(name="read_file", arguments={"path": "file"})
                    ),
                    fixture_only_effect,
                )
            except ToolError as exc:
                expected = (
                    "MCP_CONTEXT_CHANGED"
                    if mode == "rebound_revision_during_reply"
                    else "MCP_IDENTITY_UNVERIFIED"
                )
                assert mode != "unchanged" and str(exc) == expected, (mode, str(exc))
            else:
                assert mode == "unchanged" and result is fixture_result
        assert len(calls) == (1 if mode == "unchanged" else 0)

    for mode in (
        "unchanged",
        "expired_during_reply",
        "rebound_during_reply",
        "rebound_revision_during_reply",
    ):
        await decision_case(mode)
    print("TOKEN_EXPIRY_OR_REBIND_DURING_PDP_REPLY_DENIES_BEFORE_EFFECT_PASS")
    reject_invalid_claim_times(base, now)
    print("SDK_SIGNED_FIXTURE_ID_REFRESH_ACT_DELEGATION_LONG_LIFETIME_DENIED_PASS")
    print("VALID_BEARER_STILL_REQUIRES_INDEPENDENT_OWNER_AND_CEDAR_NO_PUBLIC_GRANT")


def reject_invalid_claim_times(base: dict[str, JsonValue], now: int) -> None:
    for field in ("exp", "iat", "nbf"):
        for value in (True, "123", None, float(now)):
            assert decode_verified_bearer(base | {field: value}) is None
    assert decode_verified_bearer(base | {"iat": now + 100}) is None
    assert decode_verified_bearer(base | {"nbf": now + 100}) is None
    assert decode_verified_bearer(base | {"exp": now - 1}) is None
    assert decode_verified_bearer(base | {"exp": now + 86401}) is None
    assert decode_verified_bearer(base | {"act": {"sub": "delegated"}}) is None


def test_resource_token_purpose() -> None:
    asyncio.run(main())
