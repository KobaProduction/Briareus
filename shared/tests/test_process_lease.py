"""Pure lease authority and deterministic process-control orchestration."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
import unittest
from collections.abc import Iterable
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hand_runtime import discover_source_tools
from hand_runtime._catalog import discover_source_tools as original_discover_source_tools
from hand_runtime.process_lease_application import ProcessLeaseController
from hand_runtime.process_lease_domain import (
    LeaseExpiryInput,
    LeaseIdentityInput,
    ProcessAuthority,
    ProcessInventory,
    ProcessState,
)


class MemoryProcesses(ProcessLeaseController):
    def __init__(self) -> None:
        super().__init__(1000)
        self.snapshots: list[ProcessInventory] = []
        self.actions: list[tuple[str, tuple[int, ...]]] = []

    def _processes(self) -> ProcessInventory:
        return self.snapshots.pop(0) if self.snapshots else ProcessInventory(())

    def _terminate(self, processes: Iterable[int]) -> None:
        self.actions.append(("kill", tuple(processes)))

    def _stop(self, processes: Iterable[int]) -> None:
        self.actions.append(("stop", tuple(processes)))

    def _resume(self, processes: Iterable[int]) -> None:
        self.actions.append(("resume", tuple(processes)))


class ProcessAuthorityTests(unittest.TestCase):
    def test_shape_and_bounds_are_required(self) -> None:
        invalid: tuple[tuple[LeaseIdentityInput, LeaseExpiryInput], ...] = (
            (None, 102),
            (["actor", "session", 1], 102),
            (("actor", "session"), 102),
            (("actor", 1, 1), 102),
            (("actor", "session", True), 102),
            (("", "session", 1), 102),
            (("actor", "session", 0), 102),
            (("actor", "session", 1), "102"),
            (("actor", "session", 1), 100),
            (("actor", "session", 1), 106),
            (("actor", "session", 1), float("nan")),
        )
        for identity, expiry in invalid:
            with self.subTest(identity=identity, expiry=expiry), self.assertRaises(ValueError):
                ProcessAuthority.parse(identity, expiry).require_current(100)
        ProcessAuthority.parse(("actor", "session", 1), 105).require_current(100)

    def test_lazy_catalog_export_preserves_identity(self) -> None:
        self.assertIs(discover_source_tools, original_discover_source_tools)

    def test_pure_authority_import_does_not_load_frameworks(self) -> None:
        subprocess.run(  # noqa: S603 -- fixed interpreter/argv/code; source path is a data argument
            [
                sys.executable,
                "-I",
                "-S",
                "-c",
                "import sys; sys.path.insert(0, sys.argv[1]); "
                "import hand_runtime.process_lease_domain; "
                "assert 'fastmcp' not in sys.modules; assert 'starlette' not in sys.modules",
                str(Path(__file__).resolve().parents[1]),
            ],
            check=True,
            timeout=5,
        )


class ProcessLeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_identity_resumes_and_changed_identity_kills_before_grant(self) -> None:
        lease = MemoryProcesses()
        actor = ("actor", "session", 1)
        self.assertFalse(await lease.grant(actor, time.time() + 3))
        lease.paused = True
        lease.snapshots = [ProcessInventory((ProcessState(41, "T"),))]
        self.assertTrue(await lease.grant(actor, time.time() + 3))
        self.assertEqual(lease.actions, [("resume", (41,))])
        lease.snapshots = [ProcessInventory((ProcessState(41, "R"),)), ProcessInventory(())]
        with patch("hand_runtime.process_lease_application.asyncio.sleep", new=AsyncMock()):
            self.assertFalse(await lease.grant(("other", "session", 2), time.time() + 3))
        self.assertEqual(lease.actions[-1], ("kill", (41,)))
        self.assertEqual(lease.identity, ("other", "session", 2))

    async def test_pause_requires_two_stable_stopped_observations(self) -> None:
        lease = MemoryProcesses()
        await lease.grant(("actor", "session", 1), time.time() + 3)
        lease._deadline = 0
        stopped = ProcessInventory((ProcessState(41, "T"), ProcessState(42, "t")))
        lease.snapshots = [stopped, stopped, stopped, stopped]
        with patch("hand_runtime.process_lease_application.asyncio.sleep", new=AsyncMock()):
            self.assertTrue(await lease.pause_expired())
        self.assertEqual(lease.actions, [("stop", (41, 42)), ("stop", (41, 42))])
        self.assertEqual(lease.status, "paused")

    async def test_unconfirmed_pause_and_cancellation_drop_authority_and_terminate(self) -> None:
        lease = MemoryProcesses()
        await lease.grant(("actor", "session", 1), time.time() + 3)
        lease._deadline = 0
        running = ProcessInventory((ProcessState(41, "R"),))
        lease.snapshots = [running] * 61 + [ProcessInventory(())]
        with (
            patch("hand_runtime.process_lease_application.asyncio.sleep", new=AsyncMock()),
            self.assertRaisesRegex(RuntimeError, "Worker pause could not be confirmed"),
        ):
            await lease.pause_expired()
        self.assertIsNone(lease.identity)
        self.assertEqual(lease.actions[-1], ("kill", (41,)))

        await lease.grant(("actor", "session", 1), time.time() + 3)
        lease._deadline = 0
        lease.snapshots = [running, running, ProcessInventory(())]
        with (
            patch(
                "hand_runtime.process_lease_application.asyncio.sleep",
                new=AsyncMock(side_effect=[asyncio.CancelledError, None]),
            ),
            self.assertRaises(asyncio.CancelledError),
        ):
            await lease.pause_expired()
        self.assertIsNone(lease.identity)
        self.assertEqual(lease.status, "unleased")
