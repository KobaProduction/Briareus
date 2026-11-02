"""Bind a browser proof to Access permits, authenticated Hands and event publication."""

import logging
import time
from uuid import UUID

from fastapi.responses import JSONResponse
from pydantic import ValidationError

from control_panel_api._realtime_bus import PanelEvents
from control_panel_api._runtime_access_client import RuntimeAccessClient
from control_panel_api.application.runtime_effect import (
    RuntimeFailure,
    RuntimeOutcomeUnknown,
    RuntimeStatus,
)
from control_panel_api.application.runtime_effect_contracts import (
    RuntimeHand,
    RuntimePermit,
    TerminalCommand,
)
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.infrastructure.private_runtime_codec import decode_runtime_receipt
from control_panel_api.infrastructure.runtime_replies import NativeRuntimeOutcome
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply
from runtime_peer.runtime_resource_receipts import RuntimeResources

from ._constructor_bindings import _HttpAuthorityBinding, _PeerBinding


class HttpRuntimeAuthority(_HttpAuthorityBinding):
    async def current(self, project: UUID) -> PanelContext | RuntimeFailure:
        value = await self._current(self._request, project)
        if isinstance(value, JSONResponse):
            self.rejection = value
            return RuntimeFailure(value.status_code, "CURRENT_PLATFORM_REQUIRED")
        return PanelContext(*value)


class CurrentRuntimeGrants:
    def __init__(self, access: RuntimeAccessClient) -> None:
        self._access = access

    async def prepare(
        self, context: PanelContext, command: TerminalCommand, hand: RuntimeHand
    ) -> RuntimePermit:
        return await self._access.for_actor(context.proof).prepare(
            actor=context.proof.user_uuid, hand=hand, command=command
        )

    async def resources(
        self, context: PanelContext, project: UUID, hand: RuntimeHand
    ) -> RuntimeResources:
        return await self._access.for_actor(context.proof).resources(
            actor=context.proof.user_uuid, project=project, hand=hand
        )


class PrivateRuntimeHand(_PeerBinding[PeerClient]):
    async def call(
        self, command: TerminalCommand, permit: RuntimePermit, hand: RuntimeHand
    ) -> NativeRuntimeOutcome:
        try:
            _owner_reply = await self._peer.call(
                "/internal/v1/" + hand + "/call",
                {
                    "permit": permit.permit,
                    "tool": command.tool,
                    "arguments": command.arguments.model_dump(mode="json"),
                },
                decode=successful_reply(
                    lambda value: decode_runtime_receipt(
                        value, hand=hand, tool=command.tool, operation_uuid=command.operation_uuid
                    )
                ),
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            raise RuntimeOutcomeUnknown from None
        status, body = _owner_reply.status, _owner_reply.body
        if status != 200 or body is None:
            logging.getLogger(__name__).warning("runtime owner reply status=%d", status)
            raise RuntimeOutcomeUnknown
        return body


class RuntimeCallObservations:
    def __init__(self, publisher: PanelEvents) -> None:
        self._publisher, self._began = publisher, time.monotonic()

    async def report(
        self,
        command: TerminalCommand,
        context: PanelContext,
        hand: RuntimeHand,
        status: RuntimeStatus,
        *,
        verified: bool,
    ) -> None:
        await self._publisher.publish(
            actor=context.proof.user_uuid,
            project=command.project_uuid,
            hand=hand,
            tool=command.tool if verified else "unverified",
            operation=command.operation_uuid,
            status=status,
            duration_ms=round((time.monotonic() - self._began) * 1000),
        )
