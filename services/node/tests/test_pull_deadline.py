"""A stream of progress messages must not extend the delivery phase indefinitely."""
import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch

from node_agent.docker_engine import DockerEngine,EngineFailure


class PullDeadlineTests(unittest.IsolatedAsyncioTestCase):
    def engine(self,lines):
        state={"closed":False,"calls":0}
        @asynccontextmanager
        async def stream(*args,**kwargs):
            state["calls"]+=1
            try:yield SimpleNamespace(status_code=200,aiter_lines=lines)
            finally:state["closed"]=True
        return SimpleNamespace(allowed_registries={"registry.example"},client=SimpleNamespace(stream=stream)),state

    async def test_progress_cannot_renew_total_deadline_and_stream_is_closed(self):
        async def progress():
            while True:
                await asyncio.sleep(0.001)
                yield '{"status":"downloading"}'
        engine,state=self.engine(progress)
        with patch('node_agent.docker_engine.PULL_TIMEOUT_SECONDS',0.02):
            with self.assertRaises(EngineFailure):
                await asyncio.wait_for(DockerEngine.pull_image(engine,"registry.example/module@sha256:"+"a"*64),1)
        self.assertTrue(state["closed"])
        self.assertEqual(state["calls"],1)

    async def test_successful_delivery_and_rejected_registry_do_not_retry(self):
        async def complete():yield '{"status":"complete"}'
        engine,state=self.engine(complete)
        await DockerEngine.pull_image(engine,"registry.example/module@sha256:"+"a"*64)
        with self.assertRaises(EngineFailure):
            await DockerEngine.pull_image(engine,"foreign.example/module@sha256:"+"b"*64)
        self.assertTrue(state["closed"])
        self.assertEqual(state["calls"],1)
