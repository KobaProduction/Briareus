"""Private process-owner adapter; operator authorization stays in BrowserManager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx


@dataclass(frozen=True, slots=True)
class BrowserControlState:
    running: bool
    manually_stopped: bool


class BrowserControlClient:
    def __init__(self, url: str, token: str) -> None:
        if not token:
            raise ValueError("BROWSER_CONTROL_TOKEN is required")
        self.url = url.rstrip("/")
        self.token = token

    async def command(
        self, action: Literal["state", "start", "stop", "restart"]
    ) -> BrowserControlState:
        method = "GET" if action == "state" else "POST"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(
                method,
                f"{self.url}/{action}",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Invalid Chromium lifecycle response")
        running = payload.get("running")
        stopped = payload.get("manually_stopped")
        if not isinstance(running, bool) or not isinstance(stopped, bool):
            raise ValueError("Invalid Chromium lifecycle state")
        return BrowserControlState(running, stopped)
