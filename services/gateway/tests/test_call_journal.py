import asyncio
import unittest
from unittest.mock import AsyncMock

import httpx
from bridge._call_journal import outcome
from gateway_runtime.stream import ProxyStreamingResponse


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def test_outcome_never_interprets_transport_loss_as_success(self):
        self.assertEqual(outcome(200,b'{"result":{"isError":false}}',True),"completed")
        self.assertEqual(outcome(200,b'{"result":{"isError":true}}',True),"failed")
        self.assertEqual(outcome(403,b'',True),"failed")
        self.assertEqual(outcome(200,b'{"result":{}}',False),"unknown")
        self.assertEqual(outcome(200,None,True),"unknown")

    async def test_observer_runs_once_and_reply_bytes_are_unchanged(self):
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"result":'
                yield b'{"isError":false}}'
            async def aclose(self):pass
        upstream=httpx.Response(200,stream=Body())
        slots=asyncio.Semaphore(0)
        observe=AsyncMock()
        response=ProxyStreamingResponse(upstream,slots=slots,open_responses={upstream},on_complete=observe)
        actual=b''.join([part async for part in response.body_iterator])
        await response.aclose()
        self.assertEqual(actual,b'{"result":{"isError":false}}')
        observe.assert_awaited_once_with(200,actual,True)
        self.assertEqual(slots._value,1)

    async def test_headers_only_disconnect_records_unknown_once(self):
        upstream=httpx.Response(200)
        observe=AsyncMock()
        response=ProxyStreamingResponse(upstream,slots=asyncio.Semaphore(0),open_responses={upstream},on_complete=observe)
        await response.aclose();await response.aclose()
        observe.assert_awaited_once_with(200,b'',False)
