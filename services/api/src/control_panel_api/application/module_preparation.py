"""Bounded retry of preparation without replaying user-requested effects."""

import asyncio
from typing import Protocol
from uuid import UUID, uuid4

from control_panel_api.domain.module_preparation import ModuleInitialization, ModuleTarget
from control_panel_api.domain.platform_management import RpcFailure

from .module_commands import HumanToolCommand
from .module_contracts import McpExchangeResult


class McpSession[Reply](Protocol):
    async def initialize(self, request_id: UUID) -> ModuleInitialization: ...
    async def initialized(self) -> None: ...
    async def probe(self, request_id: UUID, engine: str | None) -> McpExchangeResult[Reply]: ...
    async def call(self, command: HumanToolCommand) -> McpExchangeResult[Reply]: ...


class PreparedExchange[Reply]:
    def __init__(self, session: McpSession[Reply], target: ModuleTarget) -> None:
        self._session = session
        self._target = target

    def _preparing(self) -> RpcFailure:
        return RpcFailure(self._target.prefix.upper() + "_PREPARING")

    async def initialize(self) -> ModuleInitialization:
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            try:
                async with asyncio.timeout(max(0.01, deadline - asyncio.get_running_loop().time())):
                    # A read-only handshake retry needs fresh transport replay evidence.
                    return await self._session.initialize(uuid4())
            except RpcFailure as error:
                if "OUTCOME_UNKNOWN" not in error.code:
                    raise
            except TimeoutError:
                raise self._preparing() from None
            if asyncio.get_running_loop().time() >= deadline:
                raise self._preparing()
            await asyncio.sleep(0.5)

    async def _probe(self, status_request: bool, engine: str | None) -> Reply | None:
        reply = await self._session.probe(uuid4(), engine)
        evidence = reply.evidence
        if evidence.is_error and not evidence.node_preparing:
            if status_request:
                return reply.reply
            raise RpcFailure(self._target.prefix.upper() + "_PREPARATION_FAILED")
        if status_request and evidence.pending_operation:
            return reply.reply
        return reply.reply if evidence.ready(self._target.module, engine) else None

    async def _prepare(self, tool: str, engine: str | None) -> Reply | None:
        status_request = tool == self._target.status_tool
        deadline = asyncio.get_running_loop().time() + 10
        while True:
            try:
                reply = await self._probe(status_request, engine)
                if reply is not None:
                    return reply if status_request else None
            except RpcFailure as error:
                if "OUTCOME_UNKNOWN" not in error.code:
                    raise
            if asyncio.get_running_loop().time() >= deadline:
                raise self._preparing()
            await asyncio.sleep(0.5)

    async def run(self, command: HumanToolCommand) -> Reply:
        tool = command.tool
        selected = command.preparation_engine
        if self._target.prepares(tool, selected):
            reply = await self._prepare(
                tool, selected if self._target.module == "reverse" else None
            )
            if reply is not None:
                return reply
        return (await self._session.call(command)).reply
