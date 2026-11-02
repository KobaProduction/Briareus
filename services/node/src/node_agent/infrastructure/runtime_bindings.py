"""Existing Node native adapter constructors and container-start operation."""

from node_agent.docker_engine import DockerEngine
from node_protocol import Deployment


class _EngineBinding[EngineT]:
    def __init__(self, engine: EngineT) -> None:
        self._engine = engine


class _DeploymentBinding[EngineT]:
    def __init__(self, engine: EngineT, spec: Deployment) -> None:
        self.engine, self.spec = engine, spec


class _ContainerStart:
    engine: DockerEngine

    async def start(self, container: str, *, existing: bool) -> None:
        await self.engine.request(
            "POST", f"/containers/{container}/start", accepted=(204, 304) if existing else (204,)
        )
