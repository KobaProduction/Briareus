"""Private adapter to the external Chromium image's upstream Supervisor API."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from xmlrpc.client import Fault, dumps, loads

import httpx


@dataclass(frozen=True, slots=True)
class BrowserControlState:
    running: bool
    manually_stopped: bool


class BrowserControlClient:
    def __init__(
        self, url: str, token: str, prepare_launch: Callable[[], object] | None = None
    ) -> None:
        if not token:
            raise ValueError("BROWSER_CONTROL_TOKEN is required")
        self.url = url.rstrip("/")
        self.token = token
        self.prepare_launch = prepare_launch

    async def _rpc(
        self, client: httpx.AsyncClient, method: str, arguments: tuple[str | bool, ...]
    ) -> object:
        response = await client.post(
            self.url,
            content=dumps(arguments, methodname="supervisor." + method).encode(),
            headers={"Content-Type": "text/xml"},
            auth=httpx.BasicAuth("browser", self.token),
        )
        response.raise_for_status()
        values, _method = loads(response.content)
        if len(values) != 1:
            raise ValueError("Invalid Chromium Supervisor response")
        return values[0]

    async def _state(self, client: httpx.AsyncClient) -> BrowserControlState:
        payload = await self._rpc(client, "getProcessInfo", ("chromium",))
        if not isinstance(payload, dict) or not isinstance(payload.get("state"), int):
            raise ValueError("Invalid Chromium Supervisor state")
        state = payload["state"]
        return BrowserControlState(running=state == 20, manually_stopped=state == 0)

    async def command(
        self, action: Literal["state", "start", "stop", "restart"]
    ) -> BrowserControlState:
        async with httpx.AsyncClient(timeout=15) as client:
            state = await self._state(client)
            if action == "state" or (action == "start" and state.running):
                return state
            if action in {"start", "restart"} and self.prepare_launch is not None:
                self.prepare_launch()
            if action in {"stop", "restart"}:
                await self._change_process(client, "stopProcess", ignored_fault=70)
            if action in {"start", "restart"}:
                await self._change_process(client, "startProcess", ignored_fault=60)
            return await self._state(client)

    async def _change_process(
        self, client: httpx.AsyncClient, method: str, *, ignored_fault: int
    ) -> None:
        # Supervisor: NOT_RUNNING=70, ALREADY_STARTED=60 are idempotent outcomes.
        try:
            await self._rpc(client, method, ("chromium", True))
        except Fault as error:
            if error.faultCode != ignored_fault:
                raise
