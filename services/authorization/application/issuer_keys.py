"""Fail-closed signing-key refresh with an independently supplied loader."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol


class IssuerKeyLoader[VerifierT](Protocol):
    async def load(self) -> VerifierT: ...


class RefreshIssuerKeys[VerifierT]:
    def __init__(
        self,
        loader: IssuerKeyLoader[VerifierT],
        guard: AbstractAsyncContextManager[None],
        clock: Callable[[], float],
        ttl_seconds: float,
    ) -> None:
        if not 1 <= ttl_seconds <= 900:
            raise ValueError("bounded refresh TTL required")
        self._loader = loader
        self._guard = guard
        self._clock = clock
        self._ttl = ttl_seconds
        self._current: VerifierT | None = None
        self._expires = 0.0

    async def execute(self) -> VerifierT:
        if self._current is not None and self._clock() < self._expires:
            return self._current
        async with self._guard:
            if self._current is not None and self._clock() < self._expires:
                return self._current
            # Invalidation precedes I/O, so failed refresh cannot serve stale keys.
            self._current = None
            self._expires = 0.0
            current = await self._loader.load()
            self._current = current
            self._expires = self._clock() + self._ttl
            return current
