"""Authenticated Node/legacy Terminal resource evidence and wire codecs."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, StrictBool, StrictInt, StrictStr

from authorization._resource_scope import EffectResource, validate_effect_scope
from authorization.domain.runtime_owners import (
    RuntimeOwnerBinding,
    RuntimeOwnerScope,
    RuntimeOwnerTool,
    require_node_binding,
)
from node_protocol.effect import NodeWorkspaceBinding, NodeWorkspaceReply
from node_protocol.module_effects import (
    MODULES,
    RESOURCE_KINDS,
    TOOL_NAME,
    effect_action,
    resource_id,
)
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply


async def node_workspace(peer: PeerClient, project: UUID, module: str) -> NodeWorkspaceBinding:
    if module not in MODULES:
        raise ValueError("Approved Node module required")
    _owner_reply = await peer.call(
        "/internal/v1/resources/node-" + module + "-authority",
        {"project_uuid": str(project), "module": module},
        decode=successful_reply(NodeWorkspaceReply.model_validate),
    )
    status, reply = _owner_reply.status, _owner_reply.body
    if status != 200 or reply is None:
        raise ValueError("Current node Files binding unavailable")
    binding = reply.binding
    require_node_binding(
        project_uuid=project,
        binding_project=binding.project_uuid,
        resource_id=binding.resource_id,
        expected_resource=resource_id(module, binding.node_uuid, project, binding.workspace_uuid),
        expires_at=binding.expires_at,
        now=time.time(),
    )
    return binding


def _validate_tool(hand: str, tool: str) -> None:
    if TOOL_NAME.fullmatch(tool) is None:
        raise ValueError("Exact bounded tool selector required")
    if hand == "files":
        from node_protocol.files import READ_TOOLS, WRITE_TOOLS

        if tool not in READ_TOOLS | WRITE_TOOLS:
            raise ValueError("Unknown Files effect scope")
    elif hand == "terminal":
        from node_protocol.terminal import TOOLS

        if tool not in TOOLS:
            raise ValueError("Unknown Terminal effect scope")


class NodeRuntimeOwner:
    def __init__(self, peer: PeerClient | None, project: UUID) -> None:
        self._peer = peer
        self._project = project

    async def inspect(self, hand: str) -> RuntimeOwnerBinding:
        if hand not in MODULES or self._peer is None:
            raise ValueError("Current Node resource owner unavailable")
        binding = await node_workspace(self._peer, self._project, hand)
        return RuntimeOwnerBinding(
            self._project,
            binding.resource_id,
            binding.resource_revision,
            datetime.fromtimestamp(binding.expires_at, UTC),
        )

    def describe(self, scope: RuntimeOwnerScope) -> RuntimeOwnerTool:
        _validate_tool(scope.hand, scope.tool)
        resource = EffectResource(kind=scope.resource_kind, id=scope.resource_id)
        validate_effect_scope(scope.hand, scope.tool, scope.action, resource)
        return RuntimeOwnerTool(effect_action(scope.hand, scope.tool), RESOURCE_KINDS[scope.hand])


class TerminalReply(BaseModel):
    project_uuid: StrictStr
    isolated: StrictBool
    resource_revision: StrictInt
    resource_id: StrictStr
    tools: tuple[StrictStr, ...]


class TerminalRuntimeOwner:
    def __init__(self, peer: PeerClient, project: UUID) -> None:
        self._peer = peer
        self._project = project
        self._tools: tuple[str, ...] = ()

    async def inspect(self, hand: str) -> RuntimeOwnerBinding:
        began = datetime.now(UTC)
        _owner_reply = await self._peer.call(
            "/internal/v1/terminal/inspect",
            {},
            decode=successful_reply(TerminalReply.model_validate),
        )
        status, raw = _owner_reply.status, _owner_reply.body
        if hand != "terminal" or raw is None:
            raise ValueError("Runtime resource owner not connected")
        reply = raw
        expected = f"project-terminal:{self._project}:{reply.resource_revision:064x}"
        if (
            status != 200
            or reply.project_uuid != str(self._project)
            or reply.isolated is not True
            or reply.resource_revision < 1
            or len(reply.tools) > 32
            or reply.resource_id != expected
        ):
            raise ValueError("Current isolated Terminal owner not verified")
        self._tools = reply.tools
        return RuntimeOwnerBinding(
            self._project, reply.resource_id, reply.resource_revision, began + timedelta(seconds=5)
        )

    def describe(self, scope: RuntimeOwnerScope) -> RuntimeOwnerTool:
        if scope.hand != "terminal" or scope.tool not in self._tools:
            raise ValueError("Runtime resource owner not connected")
        resource = EffectResource(kind=scope.resource_kind, id=scope.resource_id)
        validate_effect_scope("terminal", scope.tool, scope.action, resource)
        return RuntimeOwnerTool(scope.action, "workspace")
