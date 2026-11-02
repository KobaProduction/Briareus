"""Critical storage, command-injection and expiry boundaries (not live MCP acceptance)."""

import asyncio
import base64
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from radare2_hand.application.imports import BinaryReceipt
from radare2_hand.domain.commands import native_command
from radare2_hand.runtime import MAX_BINARY, MAX_CHUNK, Analyzer, address, identifier


class AnalyzerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temporary: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.analyzer = Analyzer(self.root)

    async def asyncTearDown(self) -> None:
        await self.analyzer.close()
        self.temporary.cleanup()

    async def upload(self, data: bytes = b"static native analysis fixture\x00") -> BinaryReceipt:
        pending = await self.analyzer.start(
            "fixture.bin", hashlib.sha256(data).hexdigest(), len(data)
        )
        for offset in range(0, len(data), MAX_CHUNK):
            await self.analyzer.chunk(
                pending.upload_id,
                offset,
                base64.b64encode(data[offset : offset + MAX_CHUNK]).decode(),
            )
        return await self.analyzer.finish(pending.upload_id)

    async def test_chunked_import_digest_and_resume_after_publication_crash(self) -> None:
        data = b"test" * 4096
        result = await self.upload(data)
        self.assertEqual(result.size, len(data))
        binary = result.binary_id
        self.assertEqual(
            self.analyzer._read(self.root / "binaries" / str(binary), MAX_BINARY), data
        )
        self.assertEqual(await self.analyzer.finish(binary), result)
        # Emulate a crash after publishing bytes but before publishing metadata.
        (self.root / "binaries" / f"{binary}.json").rename(self.root / "uploads" / f"{binary}.json")
        self.assertEqual(await self.analyzer.finish(binary), result)
        self.assertEqual((await self.analyzer.listing()).binaries, (result,))

    async def test_upload_offset_and_wrong_digest_cannot_be_committed(self) -> None:
        result = await self.analyzer.start("fixture", "a" * 64, 4)
        upload = result.upload_id
        with self.assertRaises(ValueError):
            await self.analyzer.chunk(upload, 1, "dGVzdA==")
        await self.analyzer.chunk(upload, 0, "dGVzdA==")
        with self.assertRaises(ValueError):
            await self.analyzer.chunk(upload, 0, "dGVzdA==")
        with self.assertRaises(ValueError):
            await self.analyzer.finish(upload)
        await self.analyzer.abort(upload)
        self.assertFalse(list(self.root.glob("uploads/*")))

    async def test_limits_and_paths_reject_before_native_dispatch(self) -> None:
        for value in ("../private", "0x10;!id", "0x0\n!id", "file:///tmp/test"):
            with self.assertRaises((ValueError, AttributeError)):
                identifier(value)
            with self.assertRaises(ValueError):
                address(value)
        for name, size in (("../test", 1), ("ok", MAX_BINARY + 1), ("ok", True)):
            with self.assertRaises(ValueError):
                await self.analyzer.start(name, "a" * 64, size)
        result = await self.analyzer.start("ok", "a" * 64, 1)
        with self.assertRaises(ValueError):
            await self.analyzer.chunk(
                result.upload_id, 0, base64.b64encode(b"x" * (MAX_CHUNK + 1)).decode()
            )
        with self.assertRaises(ValueError):
            native_command("radare2_disassemble", uuid4(), location="0x0;!id")

    @unittest.skipUnless(os.name == "posix", "POSIX placement security boundary")
    async def test_symlink_and_hardlink_sources_are_not_analysis_data(self) -> None:
        result = await self.upload()
        binary = result.binary_id
        source = self.root / "binaries" / str(binary)
        copied = self.root / "other"
        source.rename(copied)
        source.symlink_to(copied)
        with self.assertRaises(OSError):
            await self.analyzer.native(binary, "ij", time.time() + 4)
        source.unlink()
        os.link(copied, source)
        with self.assertRaises(ValueError):
            await self.analyzer.native(binary, "ij", time.time() + 4)

    @unittest.skipUnless(os.name == "posix", "POSIX process group deadline boundary")
    async def test_expiry_and_cancellation_kill_native_child(self) -> None:
        self.analyzer.executable = sys.executable
        with self.assertRaises(TimeoutError):
            await self.analyzer._run(["-c", "import time; time.sleep(30)"], time.time() + 0.15)
        self.assertFalse(self.analyzer.processes)
        task = asyncio.create_task(
            self.analyzer._run(["-c", "import time; time.sleep(30)"], time.time() + 4)
        )
        await asyncio.sleep(0.1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(self.analyzer.processes)


if __name__ == "__main__":
    unittest.main()
