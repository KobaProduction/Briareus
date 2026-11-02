"""Fresh owner and original caller barriers follow every browser observation."""

import asyncio
from collections.abc import Callable
from typing import Protocol

from web_hand.domain.browser_snapshot import (
    BrowserSnapshot,
    BrowserSnapshotRequest,
    require_public_snapshot,
)


class TrustedBrowserSnapshotPort(Protocol):
    async def read_snapshot(self, request: BrowserSnapshotRequest) -> BrowserSnapshot: ...
    async def validate_current(self, request: BrowserSnapshotRequest) -> None: ...


class ReadBrowserSnapshot:
    def __init__(
        self,
        owner: TrustedBrowserSnapshotPort,
        original: Callable[[], BrowserSnapshotRequest],
    ) -> None:
        self.owner = owner
        self.original = original

    async def execute(self, max_chars: int) -> BrowserSnapshot:
        signed_request = self.original()
        observation = await asyncio.wait_for(self.owner.read_snapshot(signed_request), timeout=5)
        result = require_public_snapshot(observation, max_chars)
        if (
            await asyncio.wait_for(self.owner.validate_current(signed_request), timeout=3)
            is not None
        ):
            raise ValueError("browser owner post-read barrier invalid")
        if self.original() != signed_request:
            raise ValueError("original browser caller or scope changed")
        return result
