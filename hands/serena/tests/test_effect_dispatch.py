"""Freshness remains enforced around upstream dispatch, including slow calls."""

import unittest
from dataclasses import dataclass
from uuid import UUID

from serena_hand.application.dispatch_effect import DispatchEffect
from serena_hand.domain.effects import EffectAuthority, IsolationFacts

REQUEST = UUID("b44f8bd6-430c-417b-b272-018d568f088c")


@dataclass
class Clock:
    value: float = 100.0

    def now(self) -> float:
        return self.value


@dataclass
class Operation:
    clock: Clock
    calls: int = 0

    async def execute(self) -> str:
        self.calls += 1
        self.clock.value = 102.0
        return "result"


class EffectPolicyTests(unittest.TestCase):
    def test_exact_window_tool_and_uuid_are_required(self) -> None:
        for request, tool, expiry in (
            (REQUEST, "read", 100.0),
            (REQUEST, "read", 105.001),
            (REQUEST, "other", 101.0),
            (REQUEST, "read", float("nan")),
            (UUID(int=0), "read", 101.0),
        ):
            with (
                self.subTest(request=request, tool=tool, expiry=expiry),
                self.assertRaises(ValueError),
            ):
                EffectAuthority(request, tool, expiry).require_current(100, frozenset({"read"}))
        EffectAuthority(REQUEST, "read", 105.0).require_current(100, frozenset({"read"}))

    def test_isolation_needs_all_kernel_facts(self) -> None:
        IsolationFacts(1000, 1000, True, 0, True, frozenset({"lo"})).require_isolated()
        with self.assertRaises(ValueError):
            IsolationFacts(1000, 1000, True, 0, True, frozenset({"lo", "eth0"})).require_isolated()


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_expired_foreground_result_is_discarded_without_replay(self) -> None:
        clock = Clock()
        operation = Operation(clock)

        with self.assertRaises(ValueError):
            await DispatchEffect(clock, frozenset({"read"})).execute(
                EffectAuthority(REQUEST, "read", 101.0),
                operation,
            )
        self.assertEqual(operation.calls, 1)

    async def test_background_completion_outlives_initial_grant(self) -> None:
        clock = Clock()
        operation = Operation(clock)

        result = await DispatchEffect(clock, frozenset({"read"})).execute(
            EffectAuthority(REQUEST, "read", 101.0, background=True),
            operation,
        )
        self.assertEqual(result, "result")

    async def test_expired_effect_never_reaches_upstream(self) -> None:
        operation = Operation(Clock())
        with self.assertRaises(ValueError):
            await DispatchEffect(Clock(), frozenset({"read"})).execute(
                EffectAuthority(REQUEST, "read", 99.0),
                operation,
            )
        self.assertEqual(operation.calls, 0)
