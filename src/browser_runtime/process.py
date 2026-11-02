"""Chromium/Xvfb implementation. No Web MCP process owns these children."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal

from .application import BrowserProcessState
from .configuration import BrowserLaunchConfig, BrowserLaunchSource


class ChromiumProcess:
    def __init__(self, launch: BrowserLaunchSource) -> None:
        self.launch = launch
        self._process: asyncio.subprocess.Process | None = None
        self._display: asyncio.subprocess.Process | None = None
        self._manually_stopped = False
        self._lock = asyncio.Lock()

    def state(self) -> BrowserProcessState:
        process = self._process
        running = process is not None and process.returncode is None
        return BrowserProcessState(
            running,
            process.pid if process is not None and running else None,
            self._manually_stopped,
        )

    def command(self, config: BrowserLaunchConfig) -> tuple[str, ...]:
        desktop = config.desktop
        flags = [
            config.executable,
            "--no-sandbox",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=9224",
            f"--user-data-dir={config.profile}",
            f"--window-size={desktop.viewport_width},{desktop.viewport_height}",
            *config.chromium_args,
        ]
        if config.force_dark_mode:
            flags.append("--force-dark-mode")
        if config.extension_paths:
            flags.append("--load-extension=" + ",".join(config.extension_paths))
        if desktop.locale:
            flags.append(f"--lang={desktop.locale}")
        if desktop.accept_language:
            flags.append(f"--accept-lang={desktop.accept_language}")
        if desktop.headless:
            flags.append("--headless=new")
        return (*flags, "about:blank")

    async def _start_display(self, config: BrowserLaunchConfig) -> None:
        desktop = config.desktop
        if desktop.headless or not desktop.xvfb_enabled:
            return
        if self._display is not None and self._display.returncode is None:
            return
        geometry = f"{desktop.screen_width}x{desktop.screen_height}x{desktop.color_depth}"
        self._display = await asyncio.create_subprocess_exec(
            "Xvfb",
            desktop.display,
            "-screen",
            "0",
            geometry,
            "-nolisten",
            "tcp",
            "-noreset",
            start_new_session=True,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.15)

    async def start(self) -> None:
        async with self._lock:
            self._manually_stopped = False
            if self.state().running:
                return
            config = self.launch.current()
            config.profile.mkdir(parents=True, exist_ok=True)
            for name in ("config", "cache", "crash"):
                (config.profile.parent / name).mkdir(parents=True, exist_ok=True)
            for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                (config.profile / name).unlink(missing_ok=True)
            await self._start_display(config)
            environment = os.environ.copy()
            environment["DISPLAY"] = config.desktop.display
            environment["TZ"] = config.timezone
            if config.desktop.posix_locale:
                environment["LANG"] = config.desktop.posix_locale
                environment["LC_ALL"] = config.desktop.posix_locale
            self._process = await asyncio.create_subprocess_exec(
                *self.command(config),
                env=environment,
                start_new_session=True,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await self._wait_ready()
            except (OSError, RuntimeError, TimeoutError):
                await self._terminate(self._process, force=True)
                await self._terminate(self._display, force=True)
                self._process = None
                self._display = None
                raise

    async def _wait_ready(self) -> None:
        for _ in range(100):
            if not self.state().running:
                raise RuntimeError("Chromium exited during startup")
            try:
                _reader, writer = await asyncio.open_connection("127.0.0.1", 9224)
            except OSError:
                await asyncio.sleep(0.1)
                continue
            writer.close()
            await writer.wait_closed()
            return
        raise TimeoutError("Chromium debugging endpoint did not become ready")

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process | None, *, force: bool) -> None:
        if process is None or process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()

    async def stop(self, *, force: bool = False) -> None:
        async with self._lock:
            self._manually_stopped = True
            await self._terminate(self._process, force=force)
            await self._terminate(self._display, force=force)
            self._process = None
            self._display = None

    async def supervise(self) -> None:
        while True:
            await asyncio.sleep(1)
            if not self._manually_stopped and not self.state().running:
                try:
                    await self.start()
                except (OSError, RuntimeError, TimeoutError):
                    await asyncio.sleep(2)
