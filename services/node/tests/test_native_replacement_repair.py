"""Real daemon adapter decoding, stop ordering and exact stopped-worker recovery."""

import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
from node_agent.docker_engine import DockerEngine, EngineFailure, labels
from node_agent.infrastructure.container_models import ContainerInspection
from test_reconciliation import fixture

from node_protocol import Deployment

IDENTITY = "a" * 64


class NativeDaemon:
    def __init__(
        self, spec: Deployment, *, stopped: bool = False, reject_stop: bool = False
    ) -> None:
        self.spec = spec
        self.stopped, self.reject_stop = stopped, reject_stop
        self.seen: list[tuple[str, str]] = []

    def respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.51")
        self.seen.append((request.method, path))
        if (request.method, path) == ("GET", "/containers/json"):
            return httpx.Response(
                200,
                json=[
                    {
                        "Id": IDENTITY,
                        "Names": ["/" + self.spec.container_name],
                        "Labels": labels(self.spec).model_dump(by_alias=True),
                        "State": "exited" if self.stopped else "running",
                    }
                ],
            )
        if (request.method, path) == ("GET", f"/containers/{IDENTITY}/json"):
            return httpx.Response(
                200,
                json={
                    "Id": IDENTITY,
                    "Name": "/" + self.spec.container_name,
                    "Config": {"Labels": labels(self.spec).model_dump(by_alias=True)},
                    "State": {"Status": "exited" if self.stopped else "running"},
                },
            )
        if request.method == "POST" and path == f"/containers/{IDENTITY}/stop":
            return httpx.Response(500 if self.reject_stop else 204)
        if (request.method, path) in {
            ("POST", f"/containers/{IDENTITY}/start"),
            ("DELETE", f"/containers/{IDENTITY}"),
        }:
            return httpx.Response(204)
        raise AssertionError("Unexpected daemon effect: " + request.method + " " + path)

    @asynccontextmanager
    async def engine(self) -> AsyncIterator[DockerEngine]:
        # The fixture replaces the host UID check only. All native requests use
        # a mock HTTP transport; no daemon socket or host process is accessed.
        with patch("node_agent.docker_engine.os.getuid", return_value=2201, create=True):
            engine = DockerEngine(
                "/run/user/2201/docker.sock", allowed_registries=frozenset({"registry.example"})
            )
        await engine.client.aclose()
        engine.client = httpx.AsyncClient(
            transport=httpx.MockTransport(self.respond), base_url="http://node-engine/v1.51"
        )
        engine.gateway_id = "gateway"
        try:
            yield engine
        finally:
            await engine.close()


class NativeReplacementRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_rejection_never_removes_companion(self) -> None:
        _, spec = fixture()
        daemon = NativeDaemon(spec, reject_stop=True)
        async with daemon.engine() as engine:
            with patch(
                "node_agent.egress_runtime.remove_companion", new_callable=AsyncMock
            ) as remove:
                with self.assertRaises(EngineFailure):
                    await engine.remove_target(spec, IDENTITY)
                remove.assert_not_awaited()
        self.assertNotIn(("DELETE", f"/containers/{IDENTITY}"), daemon.seen)

    async def test_successful_stop_precedes_companion_and_main_removal(self) -> None:
        _, spec = fixture()
        daemon = NativeDaemon(spec)

        async def remove(
            engine: DockerEngine,
            desired: Deployment,
            current: ContainerInspection,
        ) -> None:
            del engine
            self.assertEqual(desired, spec)
            self.assertEqual(current.identity, IDENTITY)
            daemon.seen.append(("remove", "companion"))

        async with daemon.engine() as engine:
            with patch("node_agent.egress_runtime.remove_companion", side_effect=remove):
                await engine.remove_target(spec, IDENTITY)
        self.assertEqual(
            daemon.seen,
            [
                ("GET", f"/containers/{IDENTITY}/json"),
                ("POST", f"/containers/{IDENTITY}/stop"),
                ("remove", "companion"),
                ("DELETE", f"/containers/{IDENTITY}"),
            ],
        )

    async def test_stage_of_exact_running_prior_instance_restores_companion_without_new_main(
        self,
    ) -> None:
        _, original = fixture()
        spec = original.model_copy(
            update={"release": original.release.model_copy(update={"module": "web"})}
        )
        daemon = NativeDaemon(spec)
        async with daemon.engine() as engine:
            with (
                patch("node_agent.egress_runtime.ensure_execution_network", new_callable=AsyncMock),
                patch("node_agent.egress_runtime.ensure_egress", new_callable=AsyncMock) as ensure,
            ):
                self.assertEqual(await engine.stage(spec), IDENTITY)
                ensure.assert_awaited_once_with(engine, spec)
        self.assertEqual(daemon.seen, [("GET", "/containers/json")])

    async def test_stopped_applied_requires_explicit_resume_and_preserves_container(self) -> None:
        _, spec = fixture()
        daemon = NativeDaemon(spec, stopped=True)
        async with daemon.engine() as engine:
            with patch(
                "node_agent.egress_runtime.ensure_execution_network", new_callable=AsyncMock
            ):
                with self.assertRaisesRegex(EngineFailure, "explicit recovery"):
                    await engine.stage(spec)
                self.assertEqual(daemon.seen, [("GET", "/containers/json")])
                self.assertEqual(await engine.stage(spec, resume_stopped=True), IDENTITY)
        self.assertEqual(
            daemon.seen,
            [
                ("GET", "/containers/json"),
                ("GET", "/containers/json"),
                ("GET", f"/containers/{IDENTITY}/json"),
                ("POST", f"/containers/{IDENTITY}/start"),
            ],
        )
