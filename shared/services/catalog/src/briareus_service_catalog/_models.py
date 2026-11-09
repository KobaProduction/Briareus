from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,53}$")
    name: str = Field(min_length=1, max_length=80)
    group: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")

    @field_validator("group")
    @classmethod
    def public_namespace(cls, value: str) -> str:
        if value in {"api", "admin", "health"}:
            raise ValueError("Service group conflicts with a core Gateway route")
        return value

    @property
    def mcp_path(self) -> str:
        prefix = f"/{self.group}" if self.id == self.group else f"/{self.group}/{self.id}"
        return prefix + "/mcp"

    @property
    def internal_host(self) -> str:
        return f"{self.id}-mcp-hand"

    @property
    def internal_origin(self) -> str:
        return f"http://{self.internal_host}:8000"


BUILTIN_SERVICES = (
    ServiceDefinition(id="github", name="GitHub", group="svc"),
    ServiceDefinition(id="gitlab", name="GitLab", group="svc"),
    ServiceDefinition(id="server", name="Server", group="server"),
    ServiceDefinition(id="playwright", name="Playwright", group="web"),
    ServiceDefinition(id="signoz", name="SigNoz", group="observability"),
    ServiceDefinition(id="coolify", name="Coolify", group="infrastructure"),
    ServiceDefinition(id="analysis", name="Analyzer", group="analysis"),
    ServiceDefinition(id="radare2", name="radare2", group="analysis"),
    ServiceDefinition(id="analysis-g", name="Analyzer G", group="analysis"),
    ServiceDefinition(id="serena", name="Serena", group="server"),
    ServiceDefinition(id="ghidra", name="Ghidra", group="analysis"),
)


def service_definition(service_id: str) -> ServiceDefinition:
    for service in BUILTIN_SERVICES:
        if service.id == service_id:
            return service
    raise ValueError(f"Unknown service {service_id!r}; provide an explicit ServiceDefinition")
