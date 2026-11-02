"""A buffered Docker progress burst must yield before starving other control tasks."""

import asyncio
import unittest
from collections.abc import AsyncIterator
from unittest.mock import patch

import httpx
from node_agent.docker_engine import DockerEngine


class ProgressBurst(httpx.AsyncByteStream):
    def __init__(self, count: int) -> None:
        self.count = count
        self.sent = 0
        self.started = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.count):
            self.sent += 1
            self.started.set()
            yield b'{"status":"Downloading"}\n'


class PullResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    async def test_buffered_progress_allows_control_work_before_delivery_finishes(self) -> None:
        burst = ProgressBurst(1024)

        def reply(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1.51/images/create")
            return httpx.Response(200, stream=burst)

        with patch("node_agent.docker_engine.os.getuid", return_value=2201, create=True):
            engine = DockerEngine(
                "/run/user/2201/docker.sock", allowed_registries=frozenset({"registry.example"})
            )
        await engine.client.aclose()
        engine.client = httpx.AsyncClient(
            base_url="http://node-engine/v1.51", transport=httpx.MockTransport(reply)
        )
        samples: list[int] = []

        async def control_task() -> None:
            await burst.started.wait()
            samples.append(burst.sent)

        observer = asyncio.create_task(control_task())
        try:
            await asyncio.sleep(0)
            await engine.pull_image("registry.example/module@sha256:" + "a" * 64)
            await observer
            self.assertEqual(burst.sent, burst.count)
            self.assertGreater(samples[0], 0)
            self.assertLess(samples[0], burst.count)
        finally:
            observer.cancel()
            await engine.close()
