"""Protocol tests for the Web adapter to an external Supervisor process owner."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from xmlrpc.client import Fault, dumps, loads

import httpx
from briareus_web.browser_control import BrowserControlClient


class SupervisorAdapterContracts(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_lifecycle_is_idempotent_and_prepares_only_process_starts(self) -> None:
        state = 0
        methods: list[str] = []
        prepared: list[bool] = []

        def respond(request: httpx.Request) -> httpx.Response:
            nonlocal state
            self.assertEqual(request.url.path, "/RPC2")
            self.assertEqual(request.headers["authorization"], "Basic YnJvd3Nlcjp0ZXN0LXRva2Vu")
            arguments, method = loads(request.content)
            self.assertEqual(arguments[0], "chromium")
            assert method is not None
            methods.append(method)
            if method == "supervisor.getProcessInfo":
                value: object = {"state": state}
            elif method == "supervisor.startProcess":
                self.assertTrue(arguments[1])
                state, value = 20, True
            elif method == "supervisor.stopProcess":
                self.assertTrue(arguments[1])
                state, value = 0, True
            else:
                self.fail("Unexpected Supervisor method")
            return httpx.Response(200, content=dumps((value,), methodresponse=True))

        client_type = httpx.AsyncClient

        def client(*, timeout: float) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(respond), timeout=timeout)

        control = BrowserControlClient(
            "http://chromium:9001/RPC2", "test-token", lambda: prepared.append(True)
        )
        with patch("httpx.AsyncClient", side_effect=client):
            self.assertTrue((await control.command("state")).manually_stopped)
            self.assertEqual(prepared, [])
            self.assertTrue((await control.command("start")).running)
            self.assertEqual(prepared, [True])
            before = len(methods)
            self.assertTrue((await control.command("start")).running)
            self.assertEqual(methods[before:], ["supervisor.getProcessInfo"])
            self.assertEqual(prepared, [True])
            self.assertTrue((await control.command("restart")).running)
            self.assertEqual(prepared, [True, True])
            stopped = await control.command("stop")
            self.assertTrue(stopped.manually_stopped)
            self.assertFalse(stopped.running)
            self.assertEqual(prepared, [True, True])
        self.assertEqual(methods.count("supervisor.startProcess"), 2)
        self.assertEqual(methods.count("supervisor.stopProcess"), 2)

    async def test_unauthorized_control_fails_without_preparing_or_changing_the_browser(
        self,
    ) -> None:
        prepared: list[bool] = []
        client_type = httpx.AsyncClient

        def client(*, timeout: float) -> httpx.AsyncClient:
            return client_type(
                transport=httpx.MockTransport(lambda _request: httpx.Response(401)), timeout=timeout
            )

        control = BrowserControlClient(
            "http://chromium:9001/RPC2", "wrong-token", lambda: prepared.append(True)
        )
        with (
            patch("httpx.AsyncClient", side_effect=client),
            self.assertRaises(httpx.HTTPStatusError),
        ):
            await control.command("restart")
        self.assertEqual(prepared, [])

    async def test_prepare_failure_keeps_the_existing_process_running(self) -> None:
        methods: list[str | None] = []
        client_type = httpx.AsyncClient

        def respond(request: httpx.Request) -> httpx.Response:
            _arguments, method = loads(request.content)
            methods.append(method)
            return httpx.Response(200, content=dumps(({"state": 20},), methodresponse=True))

        def client(*, timeout: float) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(respond), timeout=timeout)

        def prepare() -> None:
            raise ValueError("Invalid launch manifest")

        control = BrowserControlClient("http://chromium:9001/RPC2", "test-token", prepare)
        with patch("httpx.AsyncClient", side_effect=client), self.assertRaises(ValueError):
            await control.command("restart")
        self.assertEqual(methods, ["supervisor.getProcessInfo"])

    async def test_only_upstream_not_running_fault_is_tolerated_for_idempotent_stop(self) -> None:
        client_type = httpx.AsyncClient
        methods: list[str | None] = []

        def respond(request: httpx.Request) -> httpx.Response:
            _arguments, method = loads(request.content)
            methods.append(method)
            if method == "supervisor.stopProcess":
                return httpx.Response(200, content=dumps(Fault(70, "NOT_RUNNING")))
            return httpx.Response(200, content=dumps(({"state": 0},), methodresponse=True))

        def client(*, timeout: float) -> httpx.AsyncClient:
            return client_type(transport=httpx.MockTransport(respond), timeout=timeout)

        with patch("httpx.AsyncClient", side_effect=client):
            state = await BrowserControlClient("http://chromium:9001/RPC2", "test-token").command(
                "stop"
            )
        self.assertTrue(state.manually_stopped)
        self.assertEqual(methods.count("supervisor.stopProcess"), 1)
