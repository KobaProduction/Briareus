"""Lease state uses the real process adapter with isolated inventory/signal ports."""

import signal
import time
import unittest
from typing import NamedTuple
from unittest.mock import AsyncMock, Mock, patch

import hand_runtime.process_lease as module
from hand_runtime.process_lease import ProcessLease
from hand_runtime.process_lease_application import ProcessLeaseController
from hand_runtime.process_lease_domain import ProcessInventory, ProcessState


def inventory(*states: tuple[int, str]) -> ProcessInventory:
    return ProcessInventory(tuple(ProcessState(pid, state) for pid, state in states))


class LeaseFixture(NamedTuple):
    lease: ProcessLease
    processes: Mock
    signals: Mock


class ProcessLeaseTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self) -> LeaseFixture:
        lease = ProcessLease.__new__(ProcessLease)
        ProcessLeaseController.__init__(lease, 1000)
        processes, signals = Mock(return_value=inventory()), Mock()
        self.enterContext(patch.object(lease, "_processes", processes))
        self.enterContext(patch.object(lease, "_signal", signals))
        self.enterContext(patch.object(signal, "SIGKILL", 9, create=True))
        return LeaseFixture(lease, processes, signals)

    async def test_expired_same_session_freezes_and_resumes_existing_processes(self) -> None:
        lease, processes, signals = self.fixture()
        identity = ("actor", "agent-session", 1)
        self.assertFalse(await lease.grant(identity, time.time() + 3))
        lease._deadline = 0
        running = inventory((41, "S"), (42, "R"))
        stopped = inventory((41, "T"), (42, "T"))
        processes.side_effect = [running, stopped, stopped, stopped]
        with (
            patch.object(signal, "SIGSTOP", 19, create=True),
            patch.object(module.asyncio, "sleep", AsyncMock()),
        ):
            self.assertTrue(await lease.pause_expired())
        self.assertEqual(lease.status, "paused")
        processes.side_effect = None
        processes.return_value = stopped
        with patch.object(signal, "SIGCONT", 18, create=True):
            self.assertTrue(await lease.grant(identity, time.time() + 3))
        self.assertFalse(lease.paused)
        self.assertEqual(signals.call_args.args, (stopped, 18))

    async def test_changed_actor_session_or_revision_kills_before_new_lease(self) -> None:
        for changed in (("other", "session", 1), ("actor", "other", 1), ("actor", "session", 2)):
            lease, processes, signals = self.fixture()
            lease.identity = ("actor", "session", 1)
            lease.paused = True
            stopped = inventory((41, "T"))
            processes.side_effect = [stopped, inventory()]
            with patch.object(module.asyncio, "sleep", AsyncMock()):
                self.assertFalse(await lease.grant(changed, time.time() + 3))
            self.assertEqual(signals.call_args.args, (stopped, signal.SIGKILL))
            self.assertEqual(lease.identity, changed)

    async def test_unconfirmed_pause_kills_and_drops_lease(self) -> None:
        lease, processes, signals = self.fixture()
        lease.identity = ("actor", "session", 1)
        running = inventory((41, "R"))
        processes.side_effect = [running] * 61 + [inventory()]
        with (
            patch.object(signal, "SIGSTOP", 19, create=True),
            patch.object(module.asyncio, "sleep", AsyncMock()),self.assertRaises(RuntimeError)
        ):
            await lease.pause_expired()
        self.assertIsNone(lease.identity)
        self.assertEqual(signals.call_args.args, (running, signal.SIGKILL))

    async def test_invalid_or_expired_authority_cannot_resume(self) -> None:
        lease, _, signals = self.fixture()
        for identity, expires in (
            (("actor", "session", 0), time.time() + 3),
            (("actor", "session", 1), time.time() - 1),
            (("actor", "session", 1), time.time() + 10),
        ):
            with self.assertRaises(ValueError):
                await lease.grant(identity, expires)
        signals.assert_not_called()
