"""Approved build inputs and execution contracts for independently deployed Hands."""

from dataclasses import dataclass, replace
from typing import Literal

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ArtifactLimits:
    memory_bytes: int
    cpu_millis: int
    pids: int


class ArtifactBuildInputs(BaseModel):
    dockerfile: str
    paths: list[str]
    platform: str
    build_args: dict[str, str] | None = None


@dataclass(frozen=True)
class Artifact:
    key: Literal["files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"]
    name: str
    lifecycle: Literal["stateless", "sessionful"]
    workspace: bool
    node_adapter: bool

    @property
    def storage_purpose(self) -> str:
        # Source files are intentionally shared by Files/Terminal/Git. Browser
        # cookies, infrastructure state and analysis databases must not appear
        # in that working tree or in one another's private storage.
        return {
            "files": "workspace",
            "terminal": "workspace",
            "svc": "workspace",
            "web": "browser",
            "infrastructure": "infrastructure",
            "reverse": "analysis",
            "serena": "workspace",
        }[self.key]

    @property
    def minimum_limits(self) -> ArtifactLimits:
        memory, cpu, pids = {
            "files": (128, 200, 64),
            "terminal": (256, 200, 64),
            "web": (1088, 600, 288),
            "svc": (320, 300, 96),
            "infrastructure": (320, 300, 96),
            "reverse": (1536, 750, 128),
            "serena": (512, 500, 128),
        }[self.key]
        return ArtifactLimits(memory * 1024**2, cpu, pids)

    @property
    def default_limits(self) -> ArtifactLimits:
        memory_mb = {
            "files": 256,
            "terminal": 1024,
            "web": 1536,
            "svc": 1024,
            "infrastructure": 1024,
            "reverse": 1536,
            "serena": 1024,
        }[self.key]
        minimum = self.minimum_limits
        cpu = 1500 if self.key == "web" else 1000 if self.key == "serena" else minimum.cpu_millis
        return replace(minimum, memory_bytes=memory_mb * 1024**2, cpu_millis=cpu)

    @property
    def inputs(self) -> ArtifactBuildInputs:
        inputs = ArtifactBuildInputs(
            dockerfile=f"hands/{self.key}/Dockerfile",
            paths=[
                f"hands/{self.key}/Dockerfile",
                f"hands/{self.key}/Dockerfile.dockerignore",
                f"hands/{self.key}/pyproject.toml",
                f"hands/{self.key}/uv.lock",
                f"hands/{self.key}/.python-version",
                f"hands/{self.key}/src/**",
                "shared/hand_runtime/**",
                "shared/node_protocol/**",
            ],
            platform="linux/amd64",
        )
        if self.key in {"files", "terminal", "web", "reverse", "svc", "infrastructure"}:
            inputs.paths += [
                "shared/service_runtime/**",
                "shared/project_runtime_client/**",
                "shared/owner_protocol/**",
            ]
        if self.key == "serena":
            inputs.paths += [
                "shared/service_runtime/__init__.py",
                "shared/service_runtime/_isolated_supervisor_state.py",
            ]
        if self.key in {"files", "terminal", "web", "reverse", "svc", "infrastructure", "serena"}:
            inputs.paths.append("shared/runtime_peer/**")
        if self.key in {"web"}:
            inputs.paths += ["shared/gateway_runtime/**", "hands/web/local/egress_proxy.py"]
        if self.key == "reverse":
            inputs.dockerfile = "hands/reverse/Dockerfile.node"
            inputs.paths += [
                "hands/reverse/Dockerfile.node",
                "hands/reverse/Dockerfile.node.dockerignore",
                "hands/radare2/src/radare2_hand/**",
            ]
            inputs.build_args = {
                "GHIDRA_ENGINE_IMAGE": (
                    "localhost:5500/briareus/ghidra-engine@sha256:"
                    "fdc36d77fc5ae5ff99325d52195dbc873e9978114ce8704cb5fdc0e8ed332e91"
                ),
                "GHIDRA_BRIDGE_IMAGE": (
                    "localhost:5500/briareus/ghidra-bridge@sha256:"
                    "afafc2a687b9339d706d55e335696498edcea13c20e99b9423af5cf2a5480253"
                ),
                "RADARE2_IMAGE": (
                    "localhost:5500/briareus/radare2@sha256:"
                    "eed4f715d67d5967d833d848043704cb24e070c15077cc270b17932a7723ec77"
                ),
            }
        return inputs


ARTIFACTS: dict[str, Artifact] = {
    item.key: item
    for item in (
        Artifact("files", "Файлы", "stateless", True, True),
        Artifact("terminal", "Терминал", "sessionful", True, True),
        Artifact("web", "Web", "sessionful", False, True),
        Artifact("svc", "Системы контроля версий", "stateless", True, True),
        Artifact("infrastructure", "Инфраструктура", "stateless", False, True),
        Artifact("reverse", "Анализ", "sessionful", False, True),
        Artifact("serena", "Serena", "sessionful", True, True),
    )
}


@dataclass(frozen=True)
class LogicalModule:
    key: str
    name: str
    components: tuple[str, ...]


# Analysis engines share one artifact and deployment. Development may grow
# additional components without changing the Analysis engine selection contract.
LOGICAL_MODULES = (
    LogicalModule("files", "Файлы", ("files",)),
    LogicalModule("terminal", "Терминал", ("terminal",)),
    LogicalModule("web", "Web", ("web",)),
    LogicalModule("svc", "Системы контроля версий", ("svc",)),
    LogicalModule("infrastructure", "Инфраструктура", ("infrastructure",)),
    LogicalModule("analysis", "Анализ", ("reverse",)),
    LogicalModule("development", "Разработка", ("serena",)),
)
