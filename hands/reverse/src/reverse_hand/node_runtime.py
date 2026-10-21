"""Bundled, project-private upstream Ghidra engine and MCP bridge lifecycle.

No service discovery, caller-controlled URL, global project directory or Core
credentials enter this runtime. Both upstream processes bind loopback in this
one placement. The public Hand remains the independently protected Node MCP
adapter. Script execution and remote repository connections are disabled.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from contextlib import suppress
from pathlib import Path

import httpx


class GhidraRuntime:
    def __init__(self, root: Path, memory_bytes: int):
        if root.is_symlink() or not root.is_dir():
            raise ValueError("A dedicated project analysis volume is required")
        self.root = root
        self.heap_mb = min(1024, max(256, (memory_bytes // 1024**2) - 768))
        self.engine = self.bridge = None
        self.ready = False
        for relative in ("state", "state/bridge", "projects", "artifacts", "artifacts/inbox",
                         "artifacts/exports", "artifacts/scripts", "cache", "home"):
            path = root / relative
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
            if path.is_symlink() or not path.is_dir():
                raise ValueError("Private analysis storage is not a regular directory")
            os.chmod(path, 0o700)

    def environment(self):
        return {
            "PATH": "/opt/java/openjdk/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": str(self.root / "home"), "TMPDIR": "/tmp", "LANG": "C.UTF-8",
            "JAVA_HOME": "/opt/java/openjdk", "GHIDRA_HOME": "/opt/ghidra",
            "GHIDRA_MCP_URL": "http://127.0.0.1:8089/",
            "GHIDRA_MCP_WORKER_URLS": "http://127.0.0.1:8089",
            "GHIDRA_MCP_FILE_ROOT": str(self.root / "artifacts"),
            "GHIDRA_MCP_PROJECT_ROOT": str(self.root / "projects"),
            "GHIDRA_MCP_SCRIPT_CACHE": str(self.root / "cache"),
            "GHIDRA_MCP_ALLOW_SCRIPTS": "0", "GHIDRA_MCP_WORKER_COUNT": "1",
            "GHIDRA_MCP_REQUIRE_PROGRAM_SELECTORS": "1",
            "GHIDRA_MCP_MAX_CONCURRENT_REQUESTS": "1",
            "GHIDRA_MCP_TRUSTED_HOSTS": "127.0.0.1",
            "GHIDRA_MCP_ALLOWED_HOSTS": "localhost,127.0.0.1",
            "GHIDRA_MCP_SESSION_SETTINGS_PATH": str(self.root / "state/bridge/project_session_settings.json"),
            "GHIDRA_USER": "briareus-project",
            "PYTHONPATH": "/opt/ghidra-bridge/python",
        }

    async def start(self):
        classpath = ["/opt/ghidra-engine/GhidraMCP.jar"]
        for directory in ("Framework", "Features", "Processors"):
            classpath.extend(str(path) for path in sorted(Path("/opt/ghidra/Ghidra", directory).glob("*/lib/*.jar")))
        if not all(Path(path).is_file() for path in classpath) or len(classpath) < 10:
            raise ValueError("Pinned complete Ghidra engine distribution is required")
        common = {"stdin": asyncio.subprocess.DEVNULL, "stdout": asyncio.subprocess.DEVNULL,
                  "stderr": asyncio.subprocess.DEVNULL, "start_new_session": True,
                  "env": self.environment(), "cwd": str(self.root)}
        try:
            self.engine = await asyncio.create_subprocess_exec("/opt/java/openjdk/bin/java",
                f"-Xmx{self.heap_mb}m", "-XX:+UseG1GC", "-Duser.name=briareus-project",
                "-Duser.home=" + str(self.root / "home"), "-Dghidra.home=/opt/ghidra",
                "-Dapplication.name=Briareus-project-analysis", "-classpath", ":".join(classpath),
                "com.xebyte.headless.GhidraMCPHeadlessServer", "--port", "8089", "--bind", "127.0.0.1", **common)
            deadline = time.monotonic() + 90
            async with httpx.AsyncClient(timeout=1, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if self.engine.returncode is not None:
                        raise ValueError("The private Ghidra engine exited during startup")
                    try:
                        reply = await client.get("http://127.0.0.1:8089/check_connection")
                        if reply.status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    raise ValueError("The private Ghidra engine did not become ready")
            self.bridge = await asyncio.create_subprocess_exec("/opt/ghidra-bridge/venv/bin/python",
                "-m", "bridge_mcp_ghidra", "--transport", "streamable-http", "--mcp-host", "127.0.0.1",
                "--mcp-port", "8081", "--no-lazy", **common)
            # The MCP client subsequently verifies the real upstream tool catalogue.
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if self.bridge.returncode is not None:
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
        except BaseException:
            await self.close()
            raise

    def current(self):
        return bool(self.ready and self.engine and self.bridge
                    and self.engine.returncode is None and self.bridge.returncode is None)

    async def close(self):
        self.ready = False
        for process in (self.bridge, self.engine):
            if process is None:
                continue
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
