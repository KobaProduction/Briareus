"""Native startup order and partial-failure cleanup without starting engine binaries."""

import asyncio
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from reverse_hand.application.native_runtime import StartNativeRuntime
from reverse_hand.domain.native_memory import ghidra_heap_mb
from reverse_hand.infrastructure.ghidra_runtime import GhidraProcesses


@dataclass
class NativeFixture:
    fail_at: str = ""
    cancelled: bool = False
    calls: list[str] = field(default_factory=list)

    def step(self, name: str) -> None:
        self.calls.append(name)
        if name == self.fail_at:
            if self.cancelled:
                raise asyncio.CancelledError
            raise ValueError("native fixture failure")

    async def start_engine(self) -> None:
        self.step("start_engine")

    async def await_engine(self) -> None:
        self.step("await_engine")

    async def start_bridge(self) -> None:
        self.step("start_bridge")

    async def await_bridge(self) -> None:
        self.step("await_bridge")

    async def close(self) -> None:
        self.calls.append("close")


class NativeStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_engine_ready_precedes_bridge_start(self) -> None:
        runtime = NativeFixture()
        await StartNativeRuntime(runtime).execute()
        self.assertEqual(
            runtime.calls, ["start_engine", "await_engine", "start_bridge", "await_bridge"]
        )

    async def test_every_partial_failure_closes_runtime(self) -> None:
        stages = ["start_engine", "await_engine", "start_bridge", "await_bridge"]
        for index, stage in enumerate(stages):
            with self.subTest(stage=stage):
                runtime = NativeFixture(fail_at=stage)
                with self.assertRaises(ValueError):
                    await StartNativeRuntime(runtime).execute()
                self.assertEqual(runtime.calls, [*stages[: index + 1], "close"])

    async def test_cancellation_closes_runtime_and_propagates(self) -> None:
        runtime = NativeFixture(fail_at="await_engine", cancelled=True)
        with self.assertRaises(asyncio.CancelledError):
            await StartNativeRuntime(runtime).execute()
        self.assertEqual(runtime.calls, ["start_engine", "await_engine", "close"])


class NativeEnvironmentTests(unittest.TestCase):
    def test_private_paths_and_disabled_scripts_are_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = GhidraProcesses(root, 2 * 1024**3)
            environment = runtime.environment()
            self.assertEqual(environment.HOME, str(root / "home"))
            self.assertEqual(environment.GHIDRA_MCP_PROJECT_ROOT, str(root / "projects"))
            self.assertEqual(environment.GHIDRA_MCP_ALLOW_SCRIPTS, "0")
            self.assertEqual(environment.GHIDRA_MCP_MAX_CONCURRENT_REQUESTS, "1")
            self.assertFalse(runtime.current())

    def test_heap_keeps_the_same_native_reserve_and_bounds(self) -> None:
        self.assertEqual(ghidra_heap_mb(1024**3), 256)
        self.assertEqual(ghidra_heap_mb(1536 * 1024**2), 768)
        self.assertEqual(ghidra_heap_mb(4 * 1024**3), 1024)
