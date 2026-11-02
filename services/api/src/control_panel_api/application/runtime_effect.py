"""Prepare, perform one effect and recheck both membership and durable Cedar grant."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from control_panel_api.application.approval_contracts import (
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementInvalidInput,
    OwnerManagementNotFound,
)
from control_panel_api.application.runtime_effect_contracts import (
    RuntimeEffectResult,
    RuntimeHand,
    RuntimePermit,
    RuntimeToolOutcome,
    TerminalCommand,
)
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.realtime_payloads import RuntimeStatus as RuntimeStatus
from control_panel_api.domain.runtime_effect import quick_terminal_command, runtime_actor_continues
from runtime_peer.runtime_resource_receipts import RuntimeResources
from runtime_peer.terminal_arguments import TerminalExecutionArguments


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    status: int
    code: str


class RuntimeOutcomeUnknown(Exception):
    pass


class RuntimeAuthority(Protocol):
    async def current(self, project: UUID) -> PanelContext | RuntimeFailure: ...


class RuntimeGrantPort(Protocol):
    async def prepare(
        self, context: PanelContext, command: TerminalCommand, hand: RuntimeHand
    ) -> RuntimePermit: ...

    async def resources(
        self, context: PanelContext, project: UUID, hand: RuntimeHand
    ) -> RuntimeResources: ...


class RuntimeEffectPort[Reply](Protocol):
    async def call(
        self, command: TerminalCommand, permit: RuntimePermit, hand: RuntimeHand
    ) -> RuntimeToolOutcome[Reply]: ...


class RuntimeObservations(Protocol):
    async def report(
        self,
        command: TerminalCommand,
        context: PanelContext,
        hand: RuntimeHand,
        status: RuntimeStatus,
        *,
        verified: bool,
    ) -> None: ...


def runtime_error(error: Exception) -> RuntimeFailure:
    if isinstance(error, OwnerManagementDenied):
        return RuntimeFailure(403, "RUNTIME_PERMISSION_DENIED")
    if isinstance(error, OwnerManagementConflict):
        return RuntimeFailure(409, "RUNTIME_REVISION_CONFLICT")
    if isinstance(error, OwnerManagementInvalidInput):
        return RuntimeFailure(422, "RUNTIME_SCOPE_INVALID")
    if isinstance(error, OwnerManagementNotFound):
        return RuntimeFailure(404, "RUNTIME_NOT_FOUND")
    return RuntimeFailure(503, "RUNTIME_OWNER_UNAVAILABLE")


class HumanRuntimeEffects[Reply]:
    def __init__(
        self,
        authority: RuntimeAuthority,
        grants: RuntimeGrantPort,
        owner: RuntimeEffectPort[Reply] | None,
        observations: RuntimeObservations,
    ) -> None:
        self._authority, self._grants = authority, grants
        self._owner, self._observations = owner, observations

    async def resources(
        self, project: UUID, hand: RuntimeHand
    ) -> RuntimeResources | RuntimeFailure:
        context = await self._authority.current(project)
        if isinstance(context, RuntimeFailure):
            return context
        try:
            return await self._grants.resources(context, project, hand)
        except Exception as error:
            return runtime_error(error)

    async def execute(
        self, command: TerminalCommand, hand: RuntimeHand
    ) -> RuntimeEffectResult[Reply] | RuntimeFailure:
        if self._owner is None:
            return RuntimeFailure(503, "RUNTIME_OWNER_UNAVAILABLE")
        arguments = command.arguments
        seconds = (
            arguments.observation_timeout()
            if isinstance(arguments, TerminalExecutionArguments)
            else None
        )
        if not quick_terminal_command(hand, command.tool, seconds):
            return RuntimeFailure(422, "TERMINAL_QUICK_COMMAND_LIMIT")
        context = await self._authority.current(command.project_uuid)
        if isinstance(context, RuntimeFailure):
            return context
        started = False
        try:
            permit = await self._grants.prepare(context, command, hand)
            started = True
            await self._observations.report(command, context, hand, "started", verified=True)
            result = await self._owner.call(command, permit, hand)
            return await self._release(command, hand, context, result)
        except RuntimeOutcomeUnknown:
            await self._observations.report(command, context, hand, "unknown", verified=started)
            return RuntimeFailure(503, hand.upper() + "_OUTCOME_UNKNOWN")
        except Exception as error:
            await self._observations.report(
                command, context, hand, "unknown" if started else "denied", verified=started
            )
            return runtime_error(error)

    async def _release(
        self,
        command: TerminalCommand,
        hand: RuntimeHand,
        original: PanelContext,
        result: RuntimeToolOutcome[Reply],
    ) -> RuntimeEffectResult[Reply] | RuntimeFailure:
        current = await self._authority.current(command.project_uuid)
        if isinstance(current, RuntimeFailure):
            await self._observations.report(command, original, hand, "unknown", verified=True)
            return current
        if not runtime_actor_continues(original, current):
            await self._observations.report(command, original, hand, "unknown", verified=True)
            return RuntimeFailure(403, "RUNTIME_ACTOR_CHANGED")
        await self._grants.prepare(current, command, hand)
        status: RuntimeStatus = "failed" if result.failed else "completed"
        await self._observations.report(command, original, hand, status, verified=True)
        return RuntimeEffectResult[Reply](
            operation_uuid=command.operation_uuid, result=result.result
        )
