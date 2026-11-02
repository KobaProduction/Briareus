"""Named-volume control effects, cleanup and refusal of host-backed drivers."""

import unittest
from uuid import uuid4

import httpx
from node_agent.docker_engine import EngineFailure
from node_agent.infrastructure.container_models import (
    ContainerConfiguration,
    ContainerInspection,
    ContainerSummary,
    InspectedState,
    VolumeInspection,
)
from node_agent.infrastructure.docker_commands import NetworkConnect, NetworkCreate, VolumeCreate
from node_agent.workspace_runtime import (
    initializer_config,
    prepare_workspace,
    recover_workspace_helpers,
    volume_name,
    workspace_labels,
)
from test_reconciliation import fixture

from node_protocol import Deployment, WorkspaceMount
from node_protocol.network_attestation import PublicNetworkAttestation


class Engine:
    def __init__(self) -> None:
        self.utility_image: str | None = "registry.example/node@sha256:" + "a" * 64
        self.workspace_cleanup_uncertain = False
        self.volume: VolumeInspection | None = None
        self.helper: ContainerInspection | None = None
        self.actions: list[tuple[str, str]] = []
        self.network_attestations: dict[str, PublicNetworkAttestation] = {}
        self.exit_code = 0

    async def inspect(self, container: str) -> ContainerInspection | None:
        if self.helper is not None and container != self.helper.identity:
            raise AssertionError("Exact helper identity required")
        return self.helper

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
        self.actions.append((method, path))
        if method == "GET" and path.startswith("/volumes/"):
            return (
                httpx.Response(200, content=self.volume.model_dump_json(by_alias=True))
                if self.volume
                else httpx.Response(404, json={})
            )
        if path == "/volumes/create":
            assert isinstance(payload, VolumeCreate)
            self.volume = VolumeInspection(
                name=payload.name, driver=payload.driver, labels=payload.labels, options={}
            )
            return httpx.Response(201, content=self.volume.model_dump_json(by_alias=True))
        if method == "GET" and path == "/containers/json":
            rows = (
                [
                    ContainerSummary(
                        identity=self.helper.identity,
                        names=[self.helper.name],
                        labels=self.helper.config.labels,
                    ).model_dump(by_alias=True)
                ]
                if self.helper
                else []
            )
            return httpx.Response(200, json=rows)
        if path == "/containers/create":
            assert isinstance(payload, ContainerConfiguration) and params is not None
            self.helper = helper_record(payload, str(params["name"]), "created", False)
            self.helper.config.labels["org.opencontainers.image.source"] = (
                "https://example.test/node"
            )
            return httpx.Response(201, json={"Id": self.helper.identity})
        assert self.helper is not None
        if path.endswith("/start"):
            self.helper.state = InspectedState(status="running", running=True)
            return httpx.Response(accepted[0])
        if path.endswith("/wait"):
            self.helper.state = InspectedState(status="exited", running=False)
            return httpx.Response(200, json={"StatusCode": self.exit_code})
        if path.endswith("/stop"):
            self.helper.state = InspectedState(status="exited", running=False)
            return httpx.Response(accepted[0])
        if method == "DELETE" and path.startswith("/containers/"):
            self.helper = None
            return httpx.Response(204)
        raise AssertionError("Unexpected control effect: " + path)


def helper_record(
    config: ContainerConfiguration, name: str, state: str, running: bool
) -> ContainerInspection:
    return ContainerInspection.model_validate(
        {
            "Id": "b" * 64,
            "Name": "/" + name,
            "Config": config.model_dump(by_alias=True, exclude_none=True),
            "State": {"Status": state, "Running": running},
        }
    )


class WorkspaceRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def spec(self) -> Deployment:
        _, spec = fixture()
        return spec.model_copy(update={"workspace": WorkspaceMount(id=uuid4())})

    async def test_initialize_and_failure_cleanup_preserve_volume(self) -> None:
        engine, spec = Engine(), self.spec()
        await prepare_workspace(engine, spec)
        assert engine.volume is not None
        self.assertEqual(engine.volume.name, volume_name(spec))
        self.assertIsNone(engine.helper)
        engine.exit_code = 1
        with self.assertRaises(EngineFailure):
            await prepare_workspace(engine, spec)
        self.assertIsNone(engine.helper)
        self.assertEqual(engine.volume.name, volume_name(spec))
        self.assertFalse(
            any(
                method == "DELETE" and path.startswith("/volumes")
                for method, path in engine.actions
            )
        )

    async def test_host_backed_or_foreign_volume_is_not_adopted(self) -> None:
        spec = self.spec()
        owned = VolumeInspection(
            name=volume_name(spec),
            driver="local",
            labels=workspace_labels(spec).model_dump(by_alias=True),
            options={},
        )
        for volume in (
            owned.model_copy(update={"options": {"device": "/", "type": "none", "o": "bind"}}),
            owned.model_copy(update={"labels": {}}),
            owned.model_copy(update={"driver": "nfs"}),
        ):
            engine = Engine()
            engine.volume = volume
            with self.assertRaises(EngineFailure):
                await prepare_workspace(engine, spec)
            self.assertTrue(all(method == "GET" for method, _ in engine.actions))

    async def test_helper_accepts_image_metadata_but_rejects_extra_ownership(self) -> None:
        engine, spec = Engine(), self.spec()
        assert engine.utility_image is not None
        config = initializer_config(spec, engine.utility_image)
        assert spec.workspace is not None
        engine.helper = helper_record(
            config, "briareus-workspace-init-" + spec.workspace.id.hex, "exited", False
        )
        engine.helper.config.labels["io.briareus.foreign"] = "other"
        with self.assertRaises(EngineFailure):
            await prepare_workspace(engine, spec)
        self.assertFalse(
            any(
                method in {"DELETE", "POST"} and path.startswith("/containers/")
                for method, path in engine.actions
            )
        )

    async def test_restart_reaps_only_verified_scoped_initializer(self) -> None:
        engine, spec = Engine(), self.spec()
        assert engine.utility_image is not None
        config = initializer_config(spec, engine.utility_image)
        assert spec.workspace is not None
        engine.helper = helper_record(
            config, "briareus-workspace-init-" + spec.workspace.id.hex, "running", True
        )
        await recover_workspace_helpers(engine, spec.node_uuid)
        self.assertIsNone(engine.helper)
        mutations = [path for method, path in engine.actions if method != "GET"]
        self.assertEqual(
            mutations, ["/containers/" + "b" * 64 + "/stop", "/containers/" + "b" * 64]
        )
