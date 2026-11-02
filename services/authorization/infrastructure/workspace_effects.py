"""Adapt current resource owners, Access decisions and canonical Node permits."""

import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from authorization._decision_api import (
    AuthorizationDecisionReader,
    DecisionCommand,
    VerifiedDecisionCaller,
)
from authorization._resource_scope import EffectResource
from authorization.application._reference_bindings import _KeyBinding
from authorization.domain.decisions import AuthorizedCurrentGrant
from authorization.domain.workspace_effects import (
    PrivateInvocation,
    WorkspaceBinding,
    WorkspaceCall,
    WorkspaceEffectLease,
    WorkspaceIdentity,
)
from node_protocol.control import canonical
from node_protocol.effect import (
    NodeEffectPermit,
    NodeWorkspaceBinding,
    NodeWorkspaceReply,
    sign_permit,
)
from node_protocol.module_effects import RESOURCE_KINDS, effect_action, resource_id
from node_protocol.provider_context import InvocationLease
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply


async def current_workspace_binding(
    resources: PeerClient, module: str, project_uuid: UUID
) -> WorkspaceBinding:
    owner = await resources.call(
        "/internal/v1/resources/node-" + module + "-authority",
        {"project_uuid": str(project_uuid), "module": module},
        decode=successful_reply(NodeWorkspaceReply.model_validate),
    )
    if owner.status != 200 or owner.body is None:
        raise ValueError("Current workspace binding unavailable")
    binding = owner.body.binding
    return WorkspaceBinding(
        binding.project_uuid,
        binding.node_uuid,
        binding.placement_uuid,
        binding.workspace_uuid,
        binding.resource_revision,
        binding.fingerprint,
        binding.effect_verify_key,
        binding.expires_at,
        binding.resource_id,
        resource_id(module, binding.node_uuid, binding.project_uuid, binding.workspace_uuid),
    )


class PeerWorkspaceBinding:
    def __init__(self, resources: PeerClient, call: WorkspaceCall) -> None:
        self.resources = resources
        self.call = call

    async def current(self) -> WorkspaceBinding:
        return await current_workspace_binding(
            self.resources, self.call.module, self.call.project_uuid
        )


class SqlWorkspaceGrant:
    def __init__(self, reader: AuthorizationDecisionReader, call: WorkspaceCall) -> None:
        self.reader = reader
        self.call = call

    def _decision(self, binding: WorkspaceBinding, tool: str | None) -> DecisionCommand:
        call = self.call
        if call.tool is None:
            return DecisionCommand(
                project_uuid=call.project_uuid,
                agent_session_uuid=call.agent_session_uuid,
                expected_grant_revision=call.expected_grant_revision,
                action="mcp.connect",
            )
        return DecisionCommand(
            project_uuid=call.project_uuid,
            agent_session_uuid=call.agent_session_uuid,
            expected_grant_revision=call.expected_grant_revision,
            action=effect_action(call.module, call.tool),
            hand=call.module,
            tool=tool,
            resource=EffectResource(kind=RESOURCE_KINDS[call.module], id=binding.resource_id),
        )

    async def current(
        self,
        identity: WorkspaceIdentity,
        binding: WorkspaceBinding,
        tool: str | None,
    ) -> AuthorizedCurrentGrant | None:
        decision = self._decision(binding, tool)
        caller = VerifiedDecisionCaller(
            actor_uuid=identity.actor_uuid,
            project_uuid=decision.project_uuid,
            agent_session_uuid=decision.agent_session_uuid,
            consumer="hand" if self.call.tool else "gateway",
            authority="rauthy",
            verified_peer_audience="briareus:access",
            proof_expires_at=min(
                identity.actor_expires_at,
                identity.provider_expires_at,
                datetime.fromtimestamp(binding.expires_at, UTC),
            ),
            attested_effect_key=decision.effect_key(),
        )
        return await self.reader.current_grant(decision, caller)


class PeerPrivateInvocation:
    def __init__(self, resources: PeerClient, call: WorkspaceCall, request_body: bytes) -> None:
        self.resources = resources
        self.call = call
        self._request_body = request_body

    async def current(
        self,
        identity: WorkspaceIdentity,
        binding: WorkspaceBinding,
        grant: AuthorizedCurrentGrant,
    ) -> PrivateInvocation:
        if hashlib.sha256(self._request_body).hexdigest() != self.call.body_digest:
            raise ValueError("Original MCP request binding required")
        frame: object = json.loads(self._request_body)
        if not isinstance(frame, dict) or not isinstance(frame.get("params"), dict):
            raise ValueError("Original MCP tool request required")
        parameters = frame["params"]
        arguments = parameters.get("arguments", {})
        if parameters.get("name") != self.call.tool or not isinstance(arguments, dict):
            raise ValueError("Original MCP tool arguments required")
        body = {
            "issuer": identity.issuer,
            "subject": identity.subject,
            "actor_uuid": str(identity.actor_uuid),
            "project_uuid": str(binding.project_uuid),
            "agent_session_uuid": str(self.call.agent_session_uuid),
            "grant_revision": grant.grant_revision,
            "identity_expires_at": min(
                identity.actor_expires_at,
                identity.provider_expires_at,
                grant.expires_at,
                datetime.fromtimestamp(binding.expires_at, UTC),
            ).isoformat(),
            "module": self.call.module,
            "tool": self.call.tool,
            "arguments": arguments,
            "binding": NodeWorkspaceBinding(
                node_uuid=binding.node_uuid,
                placement_uuid=binding.placement_uuid,
                project_uuid=binding.project_uuid,
                workspace_uuid=binding.workspace_uuid,
                fingerprint=binding.fingerprint,
                effect_verify_key=binding.effect_verify_key,
                expires_at=binding.expires_at,
                resource_id=binding.resource_id,
                resource_revision=binding.resource_revision,
            ).model_dump(mode="json"),
        }
        _owner_reply = await self.resources.call(
            "/internal/v1/resources/node-invocation",
            body,
            decode=successful_reply(
                lambda value: InvocationLease.model_validate_json(canonical(value))
            ),
        )
        status, reply = _owner_reply.status, _owner_reply.body
        if status == 403:
            raise InvocationAccountDenied
        if status != 200 or reply is None:
            raise ValueError("Current private invocation owner unavailable")
        return _invocation_reply(reply, binding.expires_at)


class InvocationAccountDenied(Exception):
    """Current Project account/policy selection was refused by Resources."""


def _invocation_reply(
    reply: InvocationLease,
    binding_expires_at: int,
) -> PrivateInvocation:
    expiry = reply.expires_at
    if not time.time() < expiry <= binding_expires_at:
        raise ValueError("Current private invocation owner unavailable")
    encoded = canonical(reply.context.model_dump(mode="json", exclude_unset=True))
    if not 0 < len(encoded) <= 8192:
        raise ValueError("Bounded private invocation context required")
    return PrivateInvocation(encoded, expiry)


class NodeWorkspaceEffectSigner(_KeyBinding[Ed25519PrivateKey]):
    def sign(self, lease: WorkspaceEffectLease) -> str:
        call, binding, identity = lease.call, lease.binding, lease.identity
        permit = NodeEffectPermit.model_validate(
            {
                "module": call.module,
                "node_uuid": binding.node_uuid,
                "placement_uuid": binding.placement_uuid,
                "project_uuid": binding.project_uuid,
                "workspace_uuid": binding.workspace_uuid,
                "actor_uuid": identity.actor_uuid,
                "agent_session_uuid": call.agent_session_uuid,
                "request_uuid": call.request_uuid,
                "grant_revision": lease.grant_revision,
                "fingerprint": binding.fingerprint,
                "body_digest": call.body_digest,
                "bearer_digest": call.bearer_digest,
                "arguments_digest": call.arguments_digest,
                "method": call.method,
                "tool": call.tool,
                "resource_id": binding.resource_id,
                "issued_at": lease.issued_at,
                "expires_at": lease.expires_at,
                "context_digest": lease.context_digest,
            }
        )
        return sign_permit(permit, self.key)
