from typing import Literal

from briareus_json_values import StrictModel

type JobState = Literal[
    "running", "cancelling", "completed", "failed", "cancelled", "interrupted", "timed_out"
]


class DiskUsage(StrictModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int


class ContainerResources(StrictModel):
    available: bool
    cpu_cores: float | None
    memory_bytes: int | None
    pids_limit: int | None
    pids_current: int | None
    zombie_processes: int


class UserGroup(StrictModel):
    gid: int
    name: str


class SerialDevice(StrictModel):
    path: str
    readable: bool
    writable: bool


class TerminalStatus(StrictModel):
    resources: ContainerResources
    uid: int
    gid: int
    groups: list[UserGroup]
    home: str
    workspace_root: str
    shell: str
    workspaces: int
    jobs: dict[JobState, int]
    disk: DiskUsage
    tools: dict[str, str]
    serial_devices: list[SerialDevice]
    ssh_public_keys: list[str]
    git_configured: bool


class WorkspaceSummary(StrictModel):
    workspace_id: str
    path: str
    modified_at: str
    active_jobs: int


class TerminalJob(StrictModel):
    job_id: str
    workspace_id: str
    label: str
    command: str
    cwd: str
    interactive: bool
    state: JobState
    pid: int | None
    exit_code: int | None
    signal: int | None
    created_at: str
    started_at: str
    ended_at: str | None
    duration_seconds: float
    output_bytes: int
    output_truncated: bool
    timeout_seconds: float


class WorkspaceList(StrictModel):
    workspaces: list[WorkspaceSummary]
    count: int


class JobList(StrictModel):
    jobs: list[TerminalJob]
    count: int
    total: int
    offset: int
    limit: int
    truncated: bool


class TerminalOverview(StrictModel):
    status: TerminalStatus
    workspaces: list[WorkspaceSummary]
    jobs: list[TerminalJob]


class JobTail(StrictModel):
    job_id: str
    cursor: int
    next_cursor: int
    output: str
    total_output_bytes: int
    state: JobState
    eof: bool
    output_truncated: bool


class TerminalJobView(StrictModel):
    job: TerminalJob
    tail: JobTail


class JobDeletion(StrictModel):
    job_id: str
    deleted: bool
    reason: str
    freed_bytes: int


class JobCleanup(StrictModel):
    dry_run: bool
    older_than_hours: int
    job_ids: list[str]
    count: int
    candidate_bytes: int
    freed_bytes: int
    reason: str


class WorkspaceDeletion(StrictModel):
    workspace_id: str
    deleted: bool
    freed_bytes: int
    reason: str
