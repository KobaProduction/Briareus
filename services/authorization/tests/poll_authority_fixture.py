"""Typed private peers and current identity for continuation-right HTTP boundaries."""

import base64
import json
import time
import unittest
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr
from starlette.requests import Request
from starlette.types import Message

from authorization._decision_api import (
    AuthorizedCurrentGrant,
    DecisionCommand,
    VerifiedDecisionCaller,
)
from authorization._node_files_effect import WorkspaceEffectController
from authorization._rauthy_issuer_keys import TrustedRauthyIssuerKeys
from authorization.domain.rauthy import VerifiedRauthySubject
from authorization.infrastructure.mcp_identity import CurrentIdentityResolution
from authorization.infrastructure.mcp_issuers import ConfiguredMcpIssuers
from authorization.presentation.runtime_protocol import ActorContext
from common.platform_db import PlatformDatabase, PlatformDatabaseSettings
from node_protocol.effect import NodeWorkspaceBinding, NodeWorkspaceReply
from node_protocol.module_effects import resource_id
from runtime_peer import PeerClient, VerifiedOwnerReply


class BindingOnlyPeer(PeerClient):
    def __init__(self, binding: NodeWorkspaceBinding, module: str) -> None:
        self.binding, self.module = binding, module

    async def call[ReplyT](
        self, path: str, payload: dict[str, object], *, decode: Callable[[int, object], ReplyT]
    ) -> VerifiedOwnerReply[ReplyT]:
        if path != "/internal/v1/resources/node-" + self.module + "-authority":
            raise AssertionError("Only bound resource evidence is expected")
        if payload != {"project_uuid": str(self.binding.project_uuid), "module": self.module}:
            raise AssertionError("Exact owner selection required")
        return VerifiedOwnerReply(
            200, decode(200, NodeWorkspaceReply(binding=self.binding).model_dump(mode="json"))
        )


async def check_poll_authority(
    test: unittest.IsolatedAsyncioTestCase,
    module: str,
    original_tool: str | None,
) -> None:
    node, placement, project, storage, actor, session = (uuid4() for _ in range(6))
    key = Ed25519PrivateKey.generate()
    expiry = datetime.now(UTC) + timedelta(seconds=30)
    issuer = "https://fixture.invalid/auth/v1/"
    audience = "https://fixture.invalid/hands/" + module + "/mcp"
    binding = NodeWorkspaceBinding(
        node_uuid=node,
        placement_uuid=placement,
        project_uuid=project,
        workspace_uuid=storage,
        fingerprint="a" * 64,
        resource_revision=1,
        resource_id=resource_id(module, node, project, storage),
        expires_at=int(time.time()) + 5,
        effect_verify_key=key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode(),
    )
    current = AuthorizedCurrentGrant(actor, project, session, 7, expiry)
    identity = CurrentIdentityResolution(
        ActorContext(
            issuer=issuer,
            subject="S" * 24,
            actor_uuid=actor,
            project_uuid=project,
            expires_at=expiry,
            permissions=("use_resources",),
            role="user",
        ),
        VerifiedRauthySubject("S" * 24, issuer, audience, expiry),
    )
    peer = BindingOnlyPeer(binding, module)
    database = PlatformDatabase(
        PlatformDatabaseSettings.model_validate(
            {
                "POSTGRES_HOST": "127.0.0.1",
                "POSTGRES_PORT": 1,
                "POSTGRES_DB": "briareus_access",
                "POSTGRES_USER": "fixture",
                "POSTGRES_PASSWORD": SecretStr("unused-fixture-password"),
            }
        )
    )
    test.addAsyncCleanup(database.close)
    test.enterContext(
        patch.object(database, "transaction", side_effect=AssertionError("No DB I/O expected"))
    )
    controller = WorkspaceEffectController(
        module=module,
        platform=peer,
        resources=peer,
        resolve_database=lambda: database,
        actor_model=ActorContext,
        issuers=ConfiguredMcpIssuers(
            (
                (
                    module,
                    TrustedRauthyIssuerKeys(
                        issuer=issuer, resource_audience=audience, oauth_client_id="fixture-panel"
                    ),
                ),
            )
        ),
        signing_key=key,
    )
    poll = "analysis_poll" if module == "reverse" else module + "_operation_poll"
    start = "analysis_start" if module == "reverse" else module + "_operation_start"
    arguments = {"operation_id": str(uuid4()) + ":" + str(uuid4())}
    if original_tool is not None:
        arguments["tool"] = original_tool
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": poll, "arguments": arguments},
        }
    ).encode()
    command = {
        "module": module,
        "bearer": "fixture-not-a-provider-token-" + "x" * 40,
        "decision": {
            "project_uuid": str(project),
            "agent_session_uuid": str(session),
            "action": "mcp.connect",
            "expected_grant_revision": 7,
        },
        "node_uuid": str(node),
        "placement_uuid": str(placement),
        "request_uuid": str(uuid4()),
        "fingerprint": "a" * 64,
        "body": base64.b64encode(body).decode(),
    }
    missing_rights: tuple[str | None, ...] = (
        (start, "revision", None)
        if original_tool is None
        else (original_tool, start, "revision", None)
    )
    for missing in missing_rights:
        seen: list[str] = []

        async def read(
            decision: DecisionCommand,
            caller: VerifiedDecisionCaller,
            *,
            seen_tools: list[str] = seen,
            missing_right: str | None = missing,
        ) -> AuthorizedCurrentGrant | None:
            assert decision.resource is not None and decision.tool is not None
            test.assertEqual(caller.attested_effect_key, decision.effect_key())
            test.assertEqual((decision.hand, decision.resource.id), (module, binding.resource_id))
            seen_tools.append(decision.tool)
            if decision.tool == missing_right:
                return None
            if missing_right == "revision" and decision.tool == (original_tool or start):
                return replace(current, grant_revision=8)
            return current

        async def receive() -> Message:
            return {
                "type": "http.request",
                "body": json.dumps(command).encode(),
                "more_body": False,
            }

        with (
            patch(
                "authorization._node_files_effect.current_identity",
                AsyncMock(return_value=identity),
            ),
            patch("authorization._node_files_effect.AuthorizationDecisionReader") as reader,
        ):
            reader.return_value.current_grant = AsyncMock(side_effect=read)
            request = Request(
                {
                    "type": "http",
                    "method": "POST",
                    "path": "/internal/v1/authorization/node-" + module + "-effect",
                    "headers": [],
                    "briareus.service_peer": "briareus:gateway",
                },
                receive,
            )
            response = await controller.authorize(request)
        expected = 200 if missing is None else 403
        test.assertEqual(response.status_code, expected, response.body)
        rights = (
            [poll, start]
            if original_tool is None
            else [poll, original_tool] + ([] if missing in {original_tool, "revision"} else [start])
        )
        test.assertEqual(seen, rights)
        if expected == 200:
            test.assertIn("permit", json.loads(bytes(response.body)))
