"""Resources command transport and exact action-specific result decoding."""

from urllib.parse import urlsplit
from uuid import UUID

from cryptography import x509

from control_panel_api.application.node_contracts import (
    ModuleCatalog,
    NodeDetail,
    NodeInput,
    NodeInstaller,
    NodeInventory,
    NodeOutput,
    NodePolicy,
    OperationReceipt,
    PlacementList,
    PublishedRelease,
    WorkspaceDetail,
    WorkspaceList,
)
from control_panel_api.application.node_management import NodeReceipt
from control_panel_api.domain.event_scope import EventScope
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.realtime_payloads import NodeMutation
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply

from ._constructor_bindings import _PeerBinding, _PublisherBinding


def node_output(command: NodeInput, body: object) -> NodeOutput:
    if command.action == "list":
        return NodeInventory.model_validate(body)
    if command.action == "setup":
        result = NodeInstaller.model_validate(body)
        validate_journal_setup(result)
        return result
    if command.action.startswith("runtime_policy"):
        return NodePolicy.model_validate(body)
    if command.action == "modules" and command.module is not None:
        return module_output(command.module.action, body)
    return NodeDetail.model_validate(body)


def module_output(action: str, body: object) -> NodeOutput:
    if action == "catalog":
        return ModuleCatalog.model_validate(body)
    if action == "publish":
        return PublishedRelease.model_validate(body)
    if action == "placements":
        return PlacementList.model_validate(body)
    if action == "workspaces":
        return WorkspaceList.model_validate(body)
    if action == "ensure_workspace":
        return WorkspaceDetail.model_validate(body)
    return OperationReceipt.model_validate(body)


def validate_journal_setup(result: NodeInstaller) -> None:
    journal = result.setup.journal
    target = urlsplit("//" + journal.target)
    if (
        not target.hostname
        or target.port is None
        or not 1 <= target.port <= 65535
        or target.username
        or target.password
        or target.path
        or target.query
        or target.fragment
        or "://" in journal.target
        or any(ord(character) < 33 or ord(character) > 126 for character in journal.target)
    ):
        raise ValueError("Explicit Resources journal TLS host:port required")
    if "PRIVATE KEY" in journal.ca_certificate:
        raise ValueError("Only public journal certificates may leave Core")
    certificates = x509.load_pem_x509_certificates(journal.ca_certificate.encode("ascii"))
    if not 1 <= len(certificates) <= 16:
        raise ValueError("Public journal certificate required")


class ResourcesNodes(_PeerBinding[PeerClient]):
    async def execute(self, command: NodeInput, context: PanelContext) -> NodeReceipt:
        excluded = (
            set()
            if command.action.startswith("runtime_policy")
            else {"policy_scope", "policy_values", "expected_policy_sequence"}
        )
        wire = command.model_dump(mode="json", exclude=excluded)
        wire.update(
            issuer=context.proof.issuer,
            subject=context.proof.subject,
            actor_uuid=str(context.proof.user_uuid),
            identity_expires_at=min(
                context.session.expires_at, context.proof.expires_at
            ).isoformat(),
        )
        _owner_reply = await self._peer.call(
            "/internal/v1/resources/nodes",
            wire,
            decode=successful_reply(lambda value: node_output(command, value)),
        )
        status, result = _owner_reply.status, _owner_reply.body
        return NodeReceipt(status, result)


class NodeCommittedEvents(_PublisherBinding):
    async def committed(self, command: NodeInput, result: NodeOutput, actor: UUID) -> None:
        await self._publisher.emit(
            "management.events",
            "node." + command.action,
            NodeMutation(UUID(result.item.id) if isinstance(result, NodeDetail) else None, actor),
            visibility=EventScope("operator"),
        )
