"""Deterministic lease state tests; real Linux isolation is a separate gate."""
from __future__ import annotations

import asyncio
import importlib.util
import signal
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch


source = Path(__file__).resolve().parents[3] / "shared/hand_runtime/process_lease.py"
module_spec = importlib.util.spec_from_file_location("process_lease", source)
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)


def lease_fixture():
    lease = object.__new__(module.ProcessLease)
    lease.uid, lease.identity, lease.expires_at = 1000, None, 0.0
    lease._deadline, lease.paused, lease._lock = 0.0, False, asyncio.Lock()
    lease._processes, lease._signal = Mock(return_value={}), Mock()
    return lease


class ProcessLeaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = patch.object(signal, "SIGKILL", 9, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_expired_same_session_freezes_and_resumes_existing_processes(self):
        lease = lease_fixture()
        identity = ("actor", "agent-session", 1)
        self.assertFalse(await lease.grant(identity, time.time() + 3))
        lease._deadline = 0
        lease._processes.side_effect = [{41: "S", 42: "R"}, {41: "T", 42: "T"},
                                        {41: "T", 42: "T"}, {41: "T", 42: "T"}]
        with patch.object(signal, "SIGSTOP", 19, create=True), patch.object(module.asyncio, "sleep", AsyncMock()):
            self.assertTrue(await lease.pause_expired())
        self.assertEqual(lease.status, "paused")
        lease._processes.side_effect = None
        lease._processes.return_value = {41: "T", 42: "T"}
        with patch.object(signal, "SIGCONT", 18, create=True):
            self.assertTrue(await lease.grant(identity, time.time() + 3))
        self.assertFalse(lease.paused)
        self.assertEqual(lease._signal.call_args.args[0], {41: "T", 42: "T"})

    async def test_changed_actor_session_or_revision_kills_before_new_lease(self):
        for changed in (("other", "session", 1), ("actor", "other", 1), ("actor", "session", 2)):
            lease = lease_fixture()
            lease.identity = ("actor", "session", 1)
            lease.paused = True
            lease._processes.side_effect = [{41: "T"}, {}]
            with patch.object(module.asyncio, "sleep", AsyncMock()):
                self.assertFalse(await lease.grant(changed, time.time() + 3))
            self.assertEqual(lease._signal.call_args.args, ({41: "T"}, signal.SIGKILL))
            self.assertEqual(lease.identity, changed)

    async def test_unconfirmed_pause_kills_and_drops_lease(self):
        lease = lease_fixture()
        lease.identity = ("actor", "session", 1)
        lease._processes.side_effect = [{41: "R"}] * 60 + [{41: "R"}, {}]
        with patch.object(signal, "SIGSTOP", 19, create=True), patch.object(module.asyncio, "sleep", AsyncMock()):
            with self.assertRaises(RuntimeError):
                await lease.pause_expired()
        self.assertIsNone(lease.identity)
        self.assertEqual(lease._signal.call_args.args, ({41: "R"}, signal.SIGKILL))

    async def test_invalid_or_expired_authority_cannot_resume(self):
        lease = lease_fixture()
        for identity, expires in ((("actor", "session", 0), time.time() + 3),
                                   (("actor", "session", 1), time.time() - 1),
                                   (("actor", "session", 1), time.time() + 10)):
            with self.assertRaises(ValueError):
                await lease.grant(identity, expires)
        lease._signal.assert_not_called()


if __name__ == "__main__":
    unittest.main()
