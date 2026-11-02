"""Native continuation preserves an explicitly unbounded execution deadline."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from radare2_hand.infrastructure.native_process import NativeProcesses
from radare2_hand.runtime import Analyzer


class RuntimeTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_radare_long_continuation_has_no_hidden_four_second_cap(self) -> None:
        owner = Analyzer.__new__(Analyzer)
        owner.native_process = NativeProcesses("r2")
        reader = asyncio.StreamReader()
        reader.feed_data(b"[]")
        reader.feed_eof()
        process = Mock(
            spec=asyncio.subprocess.Process,
            returncode=0,
            stdout=reader,
            wait=AsyncMock(return_value=0),
        )
        original = asyncio.timeout
        durations: list[float | None] = []

        def timeout(value: float | None) -> asyncio.Timeout:
            durations.append(value)
            return original(value)

        with (
            patch(
                "radare2_hand.infrastructure.native_process.asyncio.create_subprocess_exec",
                AsyncMock(return_value=process),
            ),
            patch(
                "radare2_hand.infrastructure.native_process.asyncio.timeout", side_effect=timeout
            ),
        ):
            result = await owner._run(["-q"], None)
        self.assertEqual(result, b"[]")
        self.assertEqual(durations, [None])
