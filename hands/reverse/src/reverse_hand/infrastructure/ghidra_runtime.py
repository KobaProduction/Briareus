"""Pinned Ghidra subprocesses, private directories, and loopback readiness adapters."""

import asyncio
import os
import signal
import tempfile
import time
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from reverse_hand.domain.native_memory import ghidra_heap_mb


@dataclass(frozen=True, slots=True)
class GhidraEnvironment:
    HOME: str
    GHIDRA_MCP_FILE_ROOT: str
    GHIDRA_MCP_PROJECT_ROOT: str
    GHIDRA_MCP_SCRIPT_CACHE: str
    GHIDRA_MCP_SESSION_SETTINGS_PATH: str
    TMPDIR: str
    PATH: str = "/opt/java/openjdk/bin:/usr/local/bin:/usr/bin:/bin"
    LANG: str = "C.UTF-8"
    JAVA_HOME: str = "/opt/java/openjdk"
    GHIDRA_HOME: str = "/opt/ghidra"
    GHIDRA_MCP_URL: str = "http://127.0.0.1:8089/"
    GHIDRA_MCP_WORKER_URLS: str = "http://127.0.0.1:8089"
    GHIDRA_MCP_ALLOW_SCRIPTS: str = "0"
    GHIDRA_MCP_WORKER_COUNT: str = "1"
    GHIDRA_MCP_REQUIRE_PROGRAM_SELECTORS: str = "1"
    GHIDRA_MCP_MAX_CONCURRENT_REQUESTS: str = "1"
    GHIDRA_MCP_TRUSTED_HOSTS: str = "127.0.0.1"
    GHIDRA_MCP_ALLOWED_HOSTS: str = "localhost,127.0.0.1"
    GHIDRA_USER: str = "briareus-project"
    PYTHONPATH: str = "/opt/ghidra-bridge/python"


class GhidraProcesses:
    def __init__(self, root: Path, memory_bytes: int) -> None:
        if root.is_symlink() or not root.is_dir():
            raise ValueError("A dedicated project analysis volume is required")
        self.root = root
        self.heap_mb = ghidra_heap_mb(memory_bytes)
        self.engine: asyncio.subprocess.Process | None = None
        self.bridge: asyncio.subprocess.Process | None = None
        self.ready = False
        for relative in (
            "state",
            "state/bridge",
            "projects",
            "artifacts",
            "artifacts/inbox",
            "artifacts/exports",
            "artifacts/scripts",
            "cache",
            "home",
        ):
            path = root / relative
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise ValueError("Private analysis storage is not a regular directory")
            os.chmod(path, 0o700)

    def environment(self) -> GhidraEnvironment:
        return GhidraEnvironment(
            HOME=str(self.root / "home"),
            GHIDRA_MCP_FILE_ROOT=str(self.root / "artifacts"),
            GHIDRA_MCP_PROJECT_ROOT=str(self.root / "projects"),
            GHIDRA_MCP_SCRIPT_CACHE=str(self.root / "cache"),
            GHIDRA_MCP_SESSION_SETTINGS_PATH=str(
                self.root / "state/bridge/project_session_settings.json"
            ),
            TMPDIR=tempfile.gettempdir(),
        )

    async def spawn(self, *arguments: str) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            env=asdict(self.environment()),
            cwd=str(self.root),
        )

    async def start_engine(self) -> None:
        classpath = await asyncio.to_thread(engine_classpath)
        self.engine = await self.spawn(
            "/opt/java/openjdk/bin/java",
            f"-Xmx{self.heap_mb}m",
            "-XX:+UseG1GC",
            "-Duser.name=briareus-project",
            "-Duser.home=" + str(self.root / "home"),
            "-Dghidra.home=/opt/ghidra",
            "-Dapplication.name=Briareus-project-analysis",
            "-classpath",
            ":".join(classpath),
            "com.xebyte.headless.GhidraMCPHeadlessServer",
            "--port",
            "8089",
            "--bind",
            "127.0.0.1",
        )

    async def await_engine(self) -> None:
        deadline = time.monotonic() + 90
        async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self.engine is None or self.engine.returncode is not None:
                    raise ValueError("The private Ghidra engine exited during startup")
                try:
                    reply = await client.get("http://127.0.0.1:8089/check_connection")
                    if reply.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.25)
        raise ValueError("The private Ghidra engine did not become ready")

    async def start_bridge(self) -> None:
        self.bridge = await self.spawn(
            "/opt/ghidra-bridge/venv/bin/python",
            "-m",
            "bridge_mcp_ghidra",
            "--transport",
            "streamable-http",
            "--mcp-host",
            "127.0.0.1",
            "--mcp-port",
            "8081",
            "--no-lazy",
        )

    async def await_bridge(self) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.bridge is None or self.bridge.returncode is not None:
                raise ValueError("The private Ghidra bridge exited during startup")
            try:
                _reader, writer = await asyncio.open_connection("127.0.0.1", 8081)
                writer.close()
                await writer.wait_closed()
                self.ready = True
                return
            except OSError:
                await asyncio.sleep(0.2)
        raise ValueError("The private Ghidra bridge did not become ready")

    def current(self) -> bool:
        return bool(
            self.ready
            and self.engine
            and self.bridge
            and self.engine.returncode is None
            and self.bridge.returncode is None
        )

    async def wait_stopped(self) -> None:
        processes = (self.engine, self.bridge)
        if any(process is None for process in processes):
            return
        waiters = [
            asyncio.create_task(process.wait()) for process in processes if process is not None
        ]
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)

    async def close(self) -> None:
        self.ready = False
        for process in (self.bridge, self.engine):
            if process is None:
                continue
            await terminate_group(process)


async def terminate_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=2)
    except TimeoutError:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()


def engine_classpath() -> tuple[str, ...]:
    classpath = ["/opt/ghidra-engine/GhidraMCP.jar"]
    for directory in ("Framework", "Features", "Processors"):
        classpath.extend(
            str(path) for path in sorted(Path("/opt/ghidra/Ghidra", directory).glob("*/lib/*.jar"))
        )
    if not all(Path(path).is_file() for path in classpath) or len(classpath) < 10:
        raise ValueError("Pinned complete Ghidra engine distribution is required")
    return tuple(classpath)
