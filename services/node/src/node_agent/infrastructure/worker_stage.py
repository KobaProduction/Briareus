"""Translate worker staging ports to exact owned native daemon operations."""

from node_agent.docker_engine import DockerEngine, EngineFailure, labels
from node_agent.domain.worker_stage import WorkerCandidate
from node_agent.runtime_profiles import SUPERVISOR_MODULES, uses_direct_network, uses_egress
from node_protocol import Deployment as Deployment

from .container_models import ContainerCreated
from .runtime_bindings import _ContainerStart, _DeploymentBinding
from .worker_config import worker_configuration


class DockerWorkerStage(_DeploymentBinding[DockerEngine], _ContainerStart):
    async def prepare_networks(self) -> None:
        from node_agent.egress_runtime import ensure_execution_network
        from node_agent.network_policy_runtime import prepare_direct_network

        if self.spec.release.module not in SUPERVISOR_MODULES or uses_egress(self.spec):
            await ensure_execution_network(self.engine, self.spec)
        if uses_direct_network(self.spec):
            self.engine.network_attestations[
                self.spec.container_name
            ] = await prepare_direct_network(self.engine, self.spec)

    async def candidates(self) -> tuple[WorkerCandidate, ...]:
        rows = await self.engine.containers(self.spec.node_uuid)
        expected = labels(self.spec).model_dump(by_alias=True)
        return tuple(
            WorkerCandidate(
                row.identity,
                all(row.labels.get(key) == value for key, value in expected.items()),
                row.state != "running",
            )
            for row in rows
            if "/" + self.spec.container_name in row.names
        )

    async def verify_resume(self, container: str) -> None:
        current = await self.engine.inspect(container)
        if current is None:
            raise EngineFailure("Applied instance changed during recovery")
        expected = labels(self.spec).model_dump(by_alias=True)
        if current.state.status not in {"exited", "created"} or any(
            current.config.labels.get(key) != value for key, value in expected.items()
        ):
            raise EngineFailure("Applied instance changed during recovery")

    async def ensure_companion(self) -> None:
        from node_agent.egress_runtime import ensure_egress

        await ensure_egress(self.engine, self.spec)

    async def create(self) -> str:
        from node_agent.workspace_runtime import prepare_workspace

        await prepare_workspace(self.engine, self.spec)
        config = worker_configuration(
            self.spec, self.engine.network_attestations.get(self.spec.container_name)
        )
        response = await self.engine.request(
            "POST",
            "/containers/create",
            accepted=(201,),
            params={"name": self.spec.container_name},
            payload=config,
        )
        return ContainerCreated.model_validate(response.json()).identity

    async def remove(self, container: str) -> None:
        await self.engine.remove_target(self.spec, container)
