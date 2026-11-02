"""Authenticated Resources transport and connection codecs."""

from uuid import UUID

from fastapi.responses import JSONResponse

from control_panel_api.application.connections import (
    ConnectionDeleted,
    ConnectionDetail,
    ConnectionFailure,
    ConnectionInput,
    ConnectionOutput,
    ConnectionPage,
    ConnectionProbe,
    ConnectionReceipt,
    ConnectionSchema,
)
from control_panel_api.domain.event_scope import EventScope
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.realtime_payloads import ConnectionMutation
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply

from ._constructor_bindings import _HttpAuthorityBinding, _PeerBinding, _PublisherBinding


class HttpConnectionAuthority(_HttpAuthorityBinding):
    async def current(self, project: UUID) -> PanelContext | ConnectionFailure:
        value = await self._current(self._request, project)
        if isinstance(value, JSONResponse):
            self.rejection = value
            return ConnectionFailure(value.status_code, "CURRENT_PLATFORM_REQUIRED")
        return PanelContext(*value)


class ResourcesConnections(_PeerBinding[PeerClient]):
    async def execute(self, command: ConnectionInput, context: PanelContext) -> ConnectionReceipt:
        data = command.model_dump(mode="json", exclude={"credential", "configuration"})
        data["configuration"] = (
            {}
            if command.configuration is None
            else command.configuration.model_dump(mode="json", exclude_unset=True)
        )
        data.update(
            credential=command.credential.get_secret_value(),
            issuer=context.proof.issuer,
            subject=context.proof.subject,
            actor_uuid=str(context.proof.user_uuid),
            identity_expires_at=min(
                context.session.expires_at, context.proof.expires_at
            ).isoformat(),
        )
        _owner_reply = await self._peer.call(
            "/internal/v1/resources/connections",
            data,
            decode=successful_reply(lambda value: self._decode(command.action, value)),
        )
        status, body = _owner_reply.status, _owner_reply.body
        if status != 200:
            return ConnectionReceipt(status)
        return ConnectionReceipt(status, body)

    @staticmethod
    def _decode(
        action: str, body: object
    ) -> ConnectionPage | ConnectionDetail | ConnectionDeleted | ConnectionProbe | ConnectionSchema:
        if action == "forms":
            return ConnectionSchema.model_validate(body)
        if action == "list":
            return ConnectionPage.model_validate(body)
        if action in {"verify", "check"}:
            return ConnectionProbe.model_validate(body)
        if action == "delete":
            return ConnectionDeleted.model_validate(body)
        return ConnectionDetail.model_validate(body)


class ConnectionCommittedEvents(_PublisherBinding):
    async def committed(
        self, command: ConnectionInput, result: ConnectionOutput, actor: UUID
    ) -> None:
        await self._publisher.emit(
            "management.events",
            "connection." + command.action,
            ConnectionMutation(
                command.project_uuid,
                result.item.id if isinstance(result, ConnectionDetail) else command.connection_uuid,
                actor,
            ),
            visibility=EventScope("project", id=command.project_uuid),
        )
