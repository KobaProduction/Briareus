"""Bounded static analysis using the pinned radare2 executable.

The MCP API never accepts a command string, path, plugin, debugger target or
URL. Uploaded binaries are data, never executed. Each native invocation gets
only fixed commands and numeric addresses; the whole process group is killed
when its current Core authority expires or the request is cancelled.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import signal
import stat
import time
from pathlib import Path
from uuid import UUID, uuid4

MAX_BINARY = 16 * 1024**2
MAX_CHUNK = 12 * 1024
MAX_STORAGE = 128 * 1024**2
MAX_OUTPUT = 900_000
MAX_ENTRIES = 64
R2_VERSION = "6.2.4"


def identifier(value: str) -> str:
    parsed = UUID(value)
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Canonical binary/upload UUID required")
    return value


def address(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,16}", value):
        raise ValueError("A hexadecimal numeric address is required")
    return hex(int(value, 16))


def bounded_int(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Numeric parameter is outside its permitted range")
    return value


def decode_chunk(value: str) -> bytes:
    if not isinstance(value, str) or not 0 < len(value) <= 4 * ((MAX_CHUNK + 2) // 3):
        raise ValueError("A bounded base64 chunk is required")
    decoded = base64.b64decode(value, validate=True)
    if not 0 < len(decoded) <= MAX_CHUNK:
        raise ValueError("Invalid binary chunk length")
    return decoded


class Analyzer:
    def __init__(self, root: Path, *, executable: str = "/usr/local/bin/radare2"):
        if not root.is_dir() or root.is_symlink():
            raise ValueError("An independently provisioned private analysis volume is required")
        self.root, self.executable = root, executable
        self.lock = asyncio.Lock()
        self.processes = set()
        self.ready = False
        for name in ("uploads", "binaries"):
            target = root / name
            target.mkdir(mode=0o700, exist_ok=True)
            if target.is_symlink() or not target.is_dir():
                raise ValueError("Private analysis directories required")
            os.chmod(target, 0o700)

    def _path(self, kind: str, value: str, suffix="") -> Path:
        return self.root / kind / (identifier(value) + suffix)

    @staticmethod
    def _read(path: Path, maximum: int) -> bytes:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            facts = os.fstat(descriptor)
            if not stat.S_ISREG(facts.st_mode) or facts.st_size > maximum or facts.st_nlink != 1:
                raise ValueError("Private bounded regular file required")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                value = stream.read(maximum + 1)
            if len(value) > maximum:
                raise ValueError("Stored analysis data exceeds limit")
            return value
        finally:
            os.close(descriptor)

    @staticmethod
    def _write(path: Path, value: bytes):
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())

    def _used(self):
        entries = list(self.root.glob("*/*"))
        if any(item.is_symlink() for item in entries):
            raise ValueError("Unexpected symlink in private analysis storage")
        return sum(item.stat().st_size for item in entries if item.is_file())

    def _manifest(self, kind, value):
        return json.loads(self._read(self._path(kind, value, ".json"), 4096))

    async def start(self, name: str, sha256: str, size: int):
        if (not isinstance(name, str) or not 0 < len(name) <= 128
            or any(ord(char) < 32 for char in name) or "/" in name or "\\" in name):
            raise ValueError("A printable binary display name is required")
        if not isinstance(sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("An exact SHA256 digest is required")
        bounded_int(size, 1, MAX_BINARY)
        async with self.lock:
            manifests = list(self.root.glob("*/*.json"))
            reserved = sum(json.loads(self._read(path, 4096))["size"] for path in manifests)
            if len(manifests) >= MAX_ENTRIES or reserved + size > MAX_STORAGE:
                raise ValueError("Private analysis storage capacity reached")
            upload = str(uuid4())
            manifest = {"name": name, "sha256": sha256, "size": size, "created_at": int(time.time())}
            self._write(self._path("uploads", upload), b"")
            try:
                self._write(self._path("uploads", upload, ".json"), json.dumps(manifest).encode())
            except BaseException:
                self._path("uploads", upload).unlink(missing_ok=True)
                raise
            return {"upload_id": upload, "size": size, "chunk_bytes": MAX_CHUNK, "offset": 0}

    async def chunk(self, upload_id: str, offset: int, content_base64: str):
        data = decode_chunk(content_base64)
        bounded_int(offset, 0, MAX_BINARY)
        async with self.lock:
            metadata = self._manifest("uploads", upload_id)
            path = self._path("uploads", upload_id)
            descriptor = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(descriptor, "r+b") as stream:
                facts = os.fstat(stream.fileno())
                if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size != offset:
                    raise ValueError("Upload offset does not match committed bytes")
                if offset + len(data) > metadata["size"]:
                    raise ValueError("Chunk exceeds declared binary length")
                stream.seek(offset)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return {"upload_id": upload_id, "offset": offset + len(data), "size": metadata["size"]}

    async def finish(self, upload_id: str):
        async with self.lock:
            # Keep the upload UUID as the opaque binary UUID. Publishing data
            # before metadata is recoverable after a crash, without replaying
            # an import under another identity or losing the original bytes.
            binary = identifier(upload_id)
            source = self._path("uploads", upload_id)
            target = self._path("binaries", binary)
            if self._path("binaries", binary, ".json").exists():
                return {"binary_id": binary, **self._manifest("binaries", binary)}
            metadata = self._manifest("uploads", upload_id)
            data = self._read(source if source.exists() else target, MAX_BINARY)
            if len(data) != metadata["size"] or hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise ValueError("Upload length or SHA256 does not match")
            if source.exists():
                if target.exists():
                    raise ValueError("Conflicting analysis import state")
                source.rename(target)
            self._path("uploads", upload_id, ".json").rename(self._path("binaries", binary, ".json"))
            # The directory entries are part of the durable import receipt.
            if os.name == "posix":
                for directory in (source.parent, target.parent):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            return {"binary_id": binary, **metadata}

    async def abort(self, upload_id: str):
        async with self.lock:
            self._manifest("uploads", upload_id)
            self._path("uploads", upload_id).unlink()
            self._path("uploads", upload_id, ".json").unlink()
            return {"upload_id": upload_id, "state": "aborted"}

    async def listing(self):
        async with self.lock:
            return {"binaries": [{"binary_id": path.stem, **self._manifest("binaries", path.stem)}
                                 for path in sorted(self.root.glob("binaries/*.json"))]}

    async def delete(self, binary_id: str):
        async with self.lock:
            self._manifest("binaries", binary_id)
            self._path("binaries", binary_id).unlink()
            self._path("binaries", binary_id, ".json").unlink()
            return {"binary_id": binary_id, "state": "deleted"}

    async def native(self, binary_id: str, command: str, deadline: float):
        # command is selected exclusively by the fixed dispatch table below.
        async with self.lock:
            metadata = self._manifest("binaries", binary_id)
            path = self._path("binaries", binary_id)
            data = self._read(path, MAX_BINARY)
            if len(data) != metadata["size"] or hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                raise ValueError("Stored binary integrity check failed")
            return await self._run(["-2", "-q", "-NN", "-S", "-e", "scr.color=0", "-e", "scr.interactive=false",
                                    "-e", "bin.demangle=false", "-c", command, str(path)], deadline)

    async def _run(self, arguments, deadline):
        if deadline is not None and deadline <= time.time():
            raise ValueError("Current analysis authority expired")
        process = await asyncio.create_subprocess_exec(self.executable, *arguments,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "TMPDIR": "/tmp",
                 "LANG": "C.UTF-8", "R2_NOPLUGINS": "1"})
        self.processes.add(process)
        try:
            async with asyncio.timeout(max(0, deadline-time.time()) if deadline is not None else None):
                output = bytearray()
                while True:
                    chunk = await process.stdout.read(65536)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > MAX_OUTPUT:
                        raise ValueError("Analysis output exceeds limit; narrow the request")
                await process.wait()
                if process.returncode != 0 or deadline is not None and deadline <= time.time():
                    raise ValueError("Native analysis did not complete under current authority")
                return bytes(output)
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
            self.processes.discard(process)

    async def startup(self):
        version = await self._run(["-v"], time.time() + 4)
        if not version.decode().splitlines()[0].startswith("radare2 " + R2_VERSION + " "):
            raise ValueError("The approved pinned radare2 version is required")
        self.ready = True

    async def close(self):
        self.ready = False
        for process in tuple(self.processes):
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        await asyncio.gather(*(process.wait() for process in tuple(self.processes)))

    async def execute(self, name, arguments, permit):
        methods = {
            "radare2_import_start": self.start, "radare2_import_chunk": self.chunk,
            "radare2_import_finish": self.finish, "radare2_import_abort": self.abort,
            "radare2_list_binaries": self.listing, "radare2_delete_binary": self.delete,
        }
        if name in methods:
            return await methods[name](**arguments)
        binary_id = arguments["binary_id"]
        if name == "radare2_binary_info":
            command = "ij"
        elif name == "radare2_functions":
            command = "aa;aflj"
        elif name == "radare2_strings":
            command = "izj"
        elif name == "radare2_disassemble":
            command = f"pdj {bounded_int(arguments.get('count', 32), 1, 256)} @ {address(arguments.get('address', '0x0'))}"
        elif name == "radare2_xrefs":
            command = f"aa;axtj @ {address(arguments['address'])}"
        else:
            raise ValueError("Unknown static analysis tool")
        result = json.loads(await self.native(binary_id, command, permit.expires_at))
        if name in {"radare2_functions", "radare2_strings"}:
            offset = bounded_int(arguments.get("offset", 0), 0, 1_000_000)
            limit = bounded_int(arguments.get("limit", 100), 1, 500)
            if not isinstance(result, list):
                raise ValueError("Unexpected native analysis collection")
            return {"binary_id": binary_id, "total": len(result), "offset": offset,
                    "items": result[offset:offset + limit]}
        return {"binary_id": binary_id, "result": result}
