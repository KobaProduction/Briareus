"""Bounded health and exact-owned companion replacement contract."""

import io
import unittest
from dataclasses import dataclass
from unittest.mock import patch
from uuid import UUID

import httpx
from node_agent.docker_engine import EngineFailure, network_name
from node_agent.egress_runtime import companion_config, companion_name, ensure_egress
from node_agent.infrastructure.container_models import (
    ContainerConfiguration,
    ContainerInspection,
    ContainerSummary,
)
from node_agent.infrastructure.docker_commands import NetworkConnect, NetworkCreate, VolumeCreate
from node_agent.runtime_profiles import EGRESS_CPU, EGRESS_MEMORY, EGRESS_PIDS, ROLE_LABEL
from test_reconciliation import fixture

from node_protocol import Deployment


@dataclass(frozen=True)
class DaemonCall:
    method: str
    path: str
    payload: ContainerConfiguration | NetworkCreate | NetworkConnect | VolumeCreate | None


class EgressFixture:
    gateway_id: str | None = None
    utility_image: str | None = "registry.example/node@sha256:" + "b" * 64
    control_addresses: tuple[str, ...] = ("172.25.80.1",)
    allowed_registries: frozenset[str] = frozenset({"registry.example"})

    def __init__(self, spec: Deployment, *, foreign: bool = False, current: bool = False) -> None:
        self.spec = spec
        self.desired = companion_config(spec, "registry.example/node@sha256:" + "b" * 64)
        self.calls: list[DaemonCall] = []
        health = self.desired.healthcheck
        assert health is not None
        self.existing = ContainerInspection.model_validate(
            {
                "Id": "old-helper",
                "Name": "/" + companion_name(spec.container_name),
                "Config": {
                    "Labels": {**self.desired.labels, ROLE_LABEL: "main" if foreign else "egress"},
                    "Healthcheck": health.model_dump(by_alias=True, exclude_none=True)
                    if current
                    else {"Test": ["CMD", "old-probe"]},
                },
            }
        )

    async def containers(self, node: UUID) -> tuple[ContainerSummary, ...]:
        if node != self.spec.node_uuid:
            raise AssertionError("Exact node inventory required")
        return (
            ContainerSummary(
                identity="old-helper", names=[self.existing.name], labels=self.desired.labels
            ),
        )

    async def inspect(self, container: str) -> ContainerInspection | None:
        if container == "old-helper":
            return self.existing
        if container != "new-helper":
            raise AssertionError("Unexpected container inspection")
        return ContainerInspection.model_validate(
            {
                "Id": container,
                "Name": self.existing.name,
                "Config": self.desired.model_dump(by_alias=True, exclude_none=True),
            }
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        accepted: tuple[int, ...] = (200,),
        params: dict[str, str | int] | None = None,
        payload: ContainerConfiguration
        | NetworkCreate
        | NetworkConnect
        | VolumeCreate
        | None = None,
    ) -> httpx.Response:
        del params
        self.calls.append(DaemonCall(method, path, payload))
        if path == "/networks":
            return httpx.Response(
                200,
                json=[
                    {
                        "Name": network_name(self.spec) + "-egress",
                        "Internal": False,
                        "Driver": "bridge",
                        "Labels": {
                            key: value
                            for key, value in self.desired.labels.items()
                            if key != "io.briareus.spec"
                        },
                    }
                ],
            )
        if path == "/containers/create":
            return httpx.Response(201, json={"Id": "new-helper"})
        return httpx.Response(accepted[0], json={})


class ProbeConnection:
    def __init__(self, status: bytes) -> None:
        self.status = status
        self.sent: list[bytes] = []

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def makefile(self, mode: str) -> io.BytesIO:
        if mode != "rb":
            raise AssertionError("Binary status line required")
        return io.BytesIO(self.status)

    def close(self) -> None:
        pass


class EgressHealthRepairTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _, self.spec = fixture()
        self.desired = companion_config(self.spec, "registry.example/node@sha256:" + "b" * 64)

    def test_probe_uses_only_socket_and_rejects_non_200(self) -> None:
        health = self.desired.healthcheck
        assert health is not None
        self.assertEqual(health.timeout, 8_000_000_000)
        self.assertEqual(health.start_period, 20_000_000_000)
        self.assertNotIn("urllib", health.test[-1])
        host = self.desired.host
        self.assertEqual(
            (host.memory, host.nano_cpus, host.pids),
            (EGRESS_MEMORY, EGRESS_CPU * 1_000_000, EGRESS_PIDS),
        )
        for status, success in (
            (b"HTTP/1.1 200 OK\r\n", True),
            (b"HTTP/1.1 503 Busy\r\n", False),
            (b"garbage 200\r\n", False),
        ):
            connection = ProbeConnection(status)
            with patch("socket.create_connection", return_value=connection) as connect:
                if success:
                    exec(health.test[-1], {})  # noqa: S102 -- exercise the generated container probe
                else:
                    with self.assertRaises(AssertionError):
                        exec(health.test[-1], {})  # noqa: S102 -- exercise the generated container probe
                connect.assert_called_once_with(("127.0.0.1", 8080), 2)
                self.assertEqual(
                    connection.sent, [b"GET /health/ready HTTP/1.0\r\nHost: localhost\r\n\r\n"]
                )

    async def test_only_owned_outdated_helper_is_replaced_with_same_alias_and_quota(self) -> None:
        engine = EgressFixture(self.spec)
        self.assertEqual(await ensure_egress(engine, self.spec), "new-helper")
        self.assertIn(
            ("POST", "/containers/old-helper/stop"),
            [(call.method, call.path) for call in engine.calls],
        )
        self.assertIn(
            ("DELETE", "/containers/old-helper"),
            [(call.method, call.path) for call in engine.calls],
        )
        create = next(call.payload for call in engine.calls if call.path == "/containers/create")
        self.assertEqual(create, self.desired)
        assert isinstance(create, ContainerConfiguration) and create.networking is not None
        self.assertEqual(
            create.networking.endpoints[network_name(self.spec)].aliases,
            ["module-egress", "web-egress"],
        )
        self.assertFalse(any(self.spec.container_name in call.path for call in engine.calls))

    async def test_foreign_inspect_labels_refuse_removal_and_current_helper_is_preserved(
        self,
    ) -> None:
        engine = EgressFixture(self.spec, foreign=True)
        with self.assertRaises(EngineFailure):
            await ensure_egress(engine, self.spec)
        self.assertFalse(any(call.method in {"POST", "DELETE"} for call in engine.calls))
        engine = EgressFixture(self.spec, current=True)
        self.assertEqual(await ensure_egress(engine, self.spec), "old-helper")
        self.assertFalse(
            any(
                call.method == "DELETE" or call.path == "/containers/create"
                for call in engine.calls
            )
        )
