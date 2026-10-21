"""Approved build inputs and execution contracts for independently deployed Hands."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    key: str
    name: str
    lifecycle: str
    workspace: bool
    node_adapter: bool

    @property
    def storage_purpose(self):
        # Source files are intentionally shared by Files/Terminal/Git. Browser
        # cookies, infrastructure state and analysis databases must not appear
        # in that working tree or in one another's private storage.
        return {"files":"workspace", "terminal":"workspace", "svc":"workspace",
                "web":"browser", "infrastructure":"infrastructure", "reverse":"analysis",
                "serena":"workspace"}[self.key]

    @property
    def minimum_limits(self):
        memory,cpu,pids={"files":(128,200,64),"terminal":(256,200,64),"web":(1088,600,288),
            "svc":(320,300,96),"infrastructure":(320,300,96),"reverse":(1536,750,128),
            "serena":(512,500,128)}[self.key]
        return {"memory_bytes":memory*1024**2,"cpu_millis":cpu,"pids":pids}

    @property
    def default_limits(self):
        memory_mb={"files":256,"terminal":1024,"web":1536,"svc":1024,
            "infrastructure":1024,"reverse":1536,"serena":1024}[self.key]
        limits = {**self.minimum_limits,"memory_bytes":memory_mb*1024**2}
        if self.key in {"web", "serena"}:
            limits["cpu_millis"] = 1500 if self.key == "web" else 1000
        return limits

    @property
    def inputs(self):
        inputs = {"dockerfile":f"hands/{self.key}/Dockerfile", "paths":[f"hands/{self.key}/Dockerfile",
            f"hands/{self.key}/Dockerfile.dockerignore",f"hands/{self.key}/pyproject.toml",f"hands/{self.key}/uv.lock",
            f"hands/{self.key}/.python-version",f"hands/{self.key}/src/**",
            "shared/hand_runtime/**","shared/node_protocol/**"], "platform":"linux/amd64"}
        if self.key in {"terminal", "svc", "infrastructure", "serena"}:
            inputs["paths"].append("shared/runtime_peer/**")
        if self.key in {"web"}:
            inputs["paths"] += ["shared/gateway_runtime/**","hands/web/local/egress_proxy.py"]
        if self.key == "reverse":
            inputs["dockerfile"] = "hands/reverse/Dockerfile.node"
            inputs["paths"] += ["hands/reverse/Dockerfile.node", "hands/reverse/Dockerfile.node.dockerignore", "hands/radare2/src/radare2_hand/**"]
            inputs["build_args"] = {
                "GHIDRA_ENGINE_IMAGE":"localhost:5500/briareus/ghidra-engine@sha256:b70dfea0c8501325e475946534c2c1e868fbba754cf296145418ddab3200d9f4",
                "GHIDRA_BRIDGE_IMAGE":"localhost:5500/briareus/ghidra-bridge@sha256:31a8ddfd14fc6f08ed32eb347c4aa3f8d60e83f7c585343b7d81efa71f8a8484",
                "RADARE2_IMAGE":"localhost:5500/briareus/radare2@sha256:89182f56f39ce11949f7c364bc202bc5e547fd4f5c8ea6df95ba8d602145d8c7",
            }
        return inputs


ARTIFACTS={item.key:item for item in (
    Artifact("files","Файлы","stateless",True,True),
    Artifact("terminal","Терминал","sessionful",True,True),
    Artifact("web","Web","sessionful",False,True),
    Artifact("svc","Системы контроля версий","stateless",True,True),
    Artifact("infrastructure","Инфраструктура","stateless",False,True),
    Artifact("reverse","Анализ","sessionful",False,True),
    Artifact("serena","Serena","sessionful",True,True),
)}


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
