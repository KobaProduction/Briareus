"""Terminal MCP read contracts owned by the Control Panel adapter."""

from pydantic import BaseModel


class DiskUsage(BaseModel):
    total_bytes: int
    used_bytes: int
    free_bytes: int


class WorkspaceSummary(BaseModel):
    workspace_id: str
    path: str
    modified_at: str | None
    active_jobs: int


class JobStatus(BaseModel):
    job_id: str
    workspace_id: str
    label: str
    command: str
    cwd: str
    interactive: bool
    state: str
    pid: int | None
    exit_code: int | None
    signal: int | None
    created_at: str | None
    started_at: str | None
    ended_at: str | None
    duration_seconds: float
    output_bytes: int
    output_truncated: bool
    timeout_seconds: float | None


class WorkspaceDeleted(BaseModel):
    workspace_id: str
    deleted: bool
    freed_bytes: int
    reason: str


class RuntimeGroup(BaseModel):
    gid: int
    name: str


class SerialDevice(BaseModel):
    path: str
    readable: bool
    writable: bool


class TerminalStatus(BaseModel):
    uid: int
    gid: int
    groups: tuple[RuntimeGroup, ...]
    home: str
    workspace_root: str
    shell: str
    workspaces: int
    jobs: dict[str, int]
    disk: DiskUsage
    tools: dict[str, str]
    serial_devices: tuple[SerialDevice, ...]
    ssh_public_keys: tuple[str, ...]
    git_configured: bool


class JobDeleted(BaseModel):
    job_id: str
    deleted: bool
    reason: str
    freed_bytes: int


class JobCleanup(BaseModel):
    dry_run: bool
    older_than_hours: int
    job_ids: tuple[str, ...]
    count: int
    candidate_bytes: int
    freed_bytes: int
    reason: str


class JobRead(BaseModel):
    job_id: str
    cursor: int
    next_cursor: int
    output: str
    total_output_bytes: int
    state: str
    eof: bool
    output_truncated: bool


class TerminalOverview(BaseModel):
    status: TerminalStatus
    workspaces: list[WorkspaceSummary]
    jobs: list[JobStatus]


class TerminalWorkspaces(BaseModel):
    workspaces: list[WorkspaceSummary]


class TerminalJobs(BaseModel):
    jobs: list[JobStatus]
