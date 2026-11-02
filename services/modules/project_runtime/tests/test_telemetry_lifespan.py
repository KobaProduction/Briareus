"""Lifecycle instrumentation preserves the SDK state and cleanup ordering."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypedDict

from modules.project_runtime.application.telemetry_lifespan import with_runtime_telemetry


@dataclass(frozen=True, slots=True)
class SessionState:
    name: str


class SessionContext(TypedDict):
    session: SessionState


class TelemetryLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_identity_and_reverse_cleanup_order_survive_failure(self) -> None:
        events: list[str] = []
        expected = SessionContext(session=SessionState("MCP session manager"))

        @asynccontextmanager
        async def original(application: str) -> AsyncIterator[SessionContext]:
            events.append(f"{application}:sdk-enter")
            try:
                yield expected
            finally:
                events.append("sdk-exit")

        @asynccontextmanager
        async def telemetry() -> AsyncIterator[None]:
            events.append("telemetry-enter")
            try:
                yield
            finally:
                events.append("telemetry-exit")

        with self.assertRaisesRegex(RuntimeError, "call failed"):
            async with with_runtime_telemetry(original, telemetry)("app") as state:
                self.assertIs(state, expected)
                events.append("call")
                raise RuntimeError("call failed")
        self.assertEqual(
            events,
            [
                "app:sdk-enter",
                "telemetry-enter",
                "call",
                "telemetry-exit",
                "sdk-exit",
            ],
        )
