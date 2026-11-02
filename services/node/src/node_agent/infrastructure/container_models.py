"""Named native create/inspect payloads; serialization stays at the daemon edge."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DockerPayload(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", populate_by_name=True)


class EmptyOptions(DockerPayload):
    pass


class PlacementLabels(DockerPayload):
    node: str = Field(alias="io.briareus.node")
    deployment: str = Field(alias="io.briareus.deployment")
    fingerprint: str = Field(alias="io.briareus.spec")


class RestartPolicy(DockerPayload):
    name: str = Field(default="no", alias="Name")


class LogConfiguration(DockerPayload):
    kind: str = Field(default="json-file", alias="Type")
    options: dict[str, str] = Field(alias="Config")


class VolumeOptions(DockerPayload):
    no_copy: bool = Field(default=True, alias="NoCopy")
    subpath: str | None = Field(default=None, alias="Subpath")


class VolumeMount(DockerPayload):
    kind: str = Field(default="volume", alias="Type")
    source: str = Field(alias="Source")
    target: str = Field(alias="Target")
    read_only: bool = Field(alias="ReadOnly")
    options: VolumeOptions = Field(default_factory=VolumeOptions, alias="VolumeOptions")


class ContainerHealthcheck(DockerPayload):
    test: list[str] = Field(alias="Test")
    interval: int | None = Field(default=None, alias="Interval")
    timeout: int | None = Field(default=None, alias="Timeout")
    start_period: int | None = Field(default=None, alias="StartPeriod")
    start_interval: int | None = Field(default=None, alias="StartInterval")
    retries: int | None = Field(default=None, alias="Retries")


class NetworkEndpoint(DockerPayload):
    aliases: list[str] = Field(alias="Aliases")


class ContainerNetworking(DockerPayload):
    endpoints: dict[str, NetworkEndpoint] = Field(alias="EndpointsConfig")


class ContainerHost(DockerPayload):
    network_mode: str = Field(alias="NetworkMode")
    memory: int = Field(alias="Memory")
    memory_swap: int = Field(alias="MemorySwap")
    nano_cpus: int = Field(alias="NanoCpus")
    pids: int = Field(alias="PidsLimit")
    cap_drop: list[str] = Field(default_factory=lambda: ["ALL"], alias="CapDrop")
    cap_add: list[str] | None = Field(default=None, alias="CapAdd")
    security: list[str] = Field(
        default_factory=lambda: ["no-new-privileges:true"], alias="SecurityOpt"
    )
    read_only: bool = Field(default=True, alias="ReadonlyRootfs")
    privileged: bool = Field(default=False, alias="Privileged")
    publish_all_ports: bool = Field(default=False, alias="PublishAllPorts")
    restart: RestartPolicy = Field(default_factory=RestartPolicy, alias="RestartPolicy")
    log: LogConfiguration = Field(alias="LogConfig")
    tmpfs: dict[str, str] | None = Field(default=None, alias="Tmpfs")
    binds: list[str] | None = Field(default=None, alias="Binds")
    mounts: list[VolumeMount] | None = Field(default=None, alias="Mounts")
    shm_size: int | None = Field(default=None, alias="ShmSize")


class ContainerConfiguration(DockerPayload):
    image: str = Field(alias="Image")
    user: str = Field(alias="User")
    labels: dict[str, str] = Field(alias="Labels")
    host: ContainerHost = Field(alias="HostConfig")
    command: list[str] | None = Field(default=None, alias="Cmd")
    environment: list[str] | None = Field(default=None, alias="Env")
    healthcheck: ContainerHealthcheck | None = Field(default=None, alias="Healthcheck")
    ports: dict[str, EmptyOptions] | None = Field(default=None, alias="ExposedPorts")
    networking: ContainerNetworking | None = Field(default=None, alias="NetworkingConfig")


class NativeRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", populate_by_name=True)


class RootlessEngineInfo(NativeRecord):
    security: list[str] = Field(default_factory=list, alias="SecurityOptions")
    cgroup_version: str = Field(default="", alias="CgroupVersion")
    cgroup_driver: str = Field(default="", alias="CgroupDriver")
    root_directory: str = Field(default="", alias="DockerRootDir")
    memory_limit: bool = Field(default=False, alias="MemoryLimit")
    pids_limit: bool = Field(default=False, alias="PidsLimit")
    cpu_quota: bool = Field(default=False, alias="CpuCfsQuota")


class PullProgress(NativeRecord):
    error: str | None = None


class ContainerSummary(NativeRecord):
    identity: str = Field(alias="Id")
    names: list[str] = Field(default_factory=list, alias="Names")
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")
    state: str = Field(default="", alias="State")


class InspectedHealthcheck(ContainerHealthcheck):
    # Docker may report an empty healthcheck; omission must remain observable.
    test: list[str] = Field(default_factory=list, alias="Test")


class InspectedConfig(NativeRecord):
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")
    image: str = Field(default="", alias="Image")
    user: str = Field(default="", alias="User")
    environment: list[str] = Field(default_factory=list, alias="Env")
    command: list[str] | None = Field(default=None, alias="Cmd")
    healthcheck: InspectedHealthcheck | None = Field(default=None, alias="Healthcheck")


class InspectedHealth(NativeRecord):
    status: str | None = Field(default=None, alias="Status")
    probe_exit_code: int | None = Field(default=None, alias="Log")

    @field_validator("status", mode="before")
    @classmethod
    def status_text(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None

    @field_validator("probe_exit_code", mode="before")
    @classmethod
    def last_probe(cls, value: object) -> int | None:
        # Never retain engine log Output: only the last bounded exit code is public.
        if not isinstance(value, list) or not value or not isinstance(value[-1], dict):
            return None
        code = value[-1].get("ExitCode")
        return code if type(code) is int and -1 <= code <= 255 else None


class InspectedState(NativeRecord):
    status: str = Field(default="", alias="Status")
    running: bool | None = Field(default=None, alias="Running")
    exit_code: int | None = Field(default=None, alias="ExitCode")
    oom_killed: bool | None = Field(default=None, alias="OOMKilled")
    error: str = Field(default="", alias="Error")
    health: InspectedHealth | None = Field(default=None, alias="Health")


class AttachedNetwork(NativeRecord):
    network_id: str = Field(default="", alias="NetworkID")
    endpoint_id: str = Field(default="", alias="EndpointID")


class InspectedNetworking(NativeRecord):
    networks: dict[str, AttachedNetwork] = Field(default_factory=dict, alias="Networks")


class InspectedMount(NativeRecord):
    kind: str = Field(alias="Type")
    source: str | None = Field(default=None, alias="Source")
    target: str = Field(alias="Target")
    read_only: bool = Field(default=False, alias="ReadOnly")


class DeviceMapping(NativeRecord):
    host: str = Field(alias="PathOnHost")
    container: str = Field(alias="PathInContainer")
    permissions: str = Field(alias="CgroupPermissions")


class DeviceRequest(NativeRecord):
    driver: str = Field(alias="Driver")
    count: int = Field(alias="Count")
    device_ids: list[str] | None = Field(default=None, alias="DeviceIDs")
    capabilities: list[list[str]] = Field(alias="Capabilities")
    options: dict[str, str] | None = Field(default=None, alias="Options")


class InspectedHost(NativeRecord):
    memory: int | None = Field(default=None, alias="Memory")
    nano_cpus: int | None = Field(default=None, alias="NanoCpus")
    pids: int | None = Field(default=None, alias="PidsLimit")
    network_mode: str | None = Field(default=None, alias="NetworkMode")
    read_only: bool | None = Field(default=None, alias="ReadonlyRootfs")
    privileged: bool | None = Field(default=None, alias="Privileged")
    cap_drop: list[str] | None = Field(default=None, alias="CapDrop")
    cap_add: list[str] | None = Field(default=None, alias="CapAdd")
    security: list[str] | None = Field(default=None, alias="SecurityOpt")
    binds: list[str] | None = Field(default=None, alias="Binds")
    mounts: list[InspectedMount] | None = Field(default=None, alias="Mounts")
    devices: list[DeviceMapping] | None = Field(default=None, alias="Devices")
    device_requests: list[DeviceRequest] | None = Field(default=None, alias="DeviceRequests")
    volumes_from: list[str] | None = Field(default=None, alias="VolumesFrom")

    def matches_isolation(self, expected: ContainerHost) -> bool:
        return (
            self.network_mode == expected.network_mode
            and self.read_only == expected.read_only
            and self.privileged == expected.privileged
            and self.cap_drop == expected.cap_drop
            and self.cap_add == expected.cap_add
            and self.security == expected.security
            and not any(
                (self.binds, self.mounts, self.devices, self.device_requests, self.volumes_from)
            )
        )


class ContainerInspection(NativeRecord):
    identity: str = Field(alias="Id")
    name: str = Field(default="", alias="Name")
    config: InspectedConfig = Field(default_factory=InspectedConfig, alias="Config")
    state: InspectedState = Field(default_factory=InspectedState, alias="State")
    network_settings: InspectedNetworking = Field(
        default_factory=InspectedNetworking, alias="NetworkSettings"
    )
    host: InspectedHost = Field(default_factory=InspectedHost, alias="HostConfig")


class ContainerCreated(NativeRecord):
    identity: str = Field(alias="Id")


class DaemonError(NativeRecord):
    message: str = Field(default="", alias="Message")


class ContainerExit(NativeRecord):
    status: int = Field(alias="StatusCode")
    error: DaemonError | None = Field(default=None, alias="Error")

    @field_validator("error", mode="before")
    @classmethod
    def empty_error(cls, value: object) -> DaemonError | None:
        return DaemonError.model_validate(value) if value else None


class VolumeInspection(NativeRecord):
    name: str = Field(default="", alias="Name")
    driver: str = Field(default="", alias="Driver")
    options: dict[str, str] | None = Field(default=None, alias="Options")
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")
