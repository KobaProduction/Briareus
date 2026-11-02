"""Terminal result projections shared by the producer and its transport consumers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiskUsage:
    total_bytes: int
    used_bytes: int
    free_bytes: int


@dataclass(frozen=True, slots=True)
class WorkspaceCreated:
    workspace_id: str
    path: str
    created: bool


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    workspace_id: str
    path: str
    modified_at: str | None
    active_jobs: int


@dataclass(frozen=True, slots=True)
class WorkspaceList:
    workspaces: tuple[WorkspaceSummary, ...]
    count: int


@dataclass(frozen=True, slots=True)
class JobStatus:
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


@dataclass(frozen=True, slots=True)
class WorkspaceInfo:
    workspace_id: str
    path: str
    modified_at: str | None
    disk: DiskUsage
    jobs: tuple[JobStatus, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceDeleted:
    workspace_id: str
    deleted: bool
    freed_bytes: int
    reason: str


@dataclass(frozen=True, slots=True)
class RuntimeGroup:
    gid: int
    name: str


@dataclass(frozen=True, slots=True)
class SerialDevice:
    path: str
    readable: bool
    writable: bool


@dataclass(frozen=True, slots=True)
class TerminalStatus:
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


@dataclass(frozen=True, slots=True)
class JobList:
    jobs: tuple[JobStatus, ...]
    count: int
    total: int
    offset: int
    limit: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class JobDeleted:
    job_id: str
    deleted: bool
    reason: str
    freed_bytes: int


@dataclass(frozen=True, slots=True)
class JobCleanup:
    dry_run: bool
    older_than_hours: int
    job_ids: tuple[str, ...]
    count: int
    candidate_bytes: int
    freed_bytes: int
    reason: str


@dataclass(frozen=True, slots=True)
class JobRead:
    job_id: str
    cursor: int
    next_cursor: int
    output: str
    total_output_bytes: int
    state: str
    eof: bool
    output_truncated: bool


@dataclass(frozen=True, slots=True)
class JobWrite:
    job_id: str
    written_bytes: int
    backpressured: bool


@dataclass(frozen=True, slots=True)
class JobResize:
    job_id: str
    cols: int
    rows: int


@dataclass(frozen=True, slots=True)
class JobExecution(JobStatus):
    stdout: str
    stderr: str
    output: str
    output_stream: str
    next_cursor: int
    eof: bool
    stdout_truncated: bool
    stderr_truncated: bool
    timed_out: bool


@dataclass(frozen=True, slots=True)
class DirectExecution:
    workspace_id: str
    command: str
    cwd: str
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    started_at: str | None
    ended_at: str | None
    duration_seconds: float
    timeout_seconds: float


type TerminalReceipt = (
    WorkspaceCreated
    | WorkspaceList
    | WorkspaceInfo
    | WorkspaceDeleted
    | TerminalStatus
    | JobStatus
    | JobList
    | JobDeleted
    | JobCleanup
    | JobRead
    | JobWrite
    | JobResize
    | JobExecution
    | DirectExecution
)

# Each public tool has one concrete receipt, including the richer execution result.
TERMINAL_RESULTS: dict[str, type[TerminalReceipt]] = {
    "terminal_status": TerminalStatus,
    "workspace_list": WorkspaceList,
    "workspace_create": WorkspaceCreated,
    "workspace_info": WorkspaceInfo,
    "workspace_delete": WorkspaceDeleted,
    "terminal_exec": JobExecution,
    "job_start": JobStatus,
    "job_status": JobStatus,
    "job_list": JobList,
    "job_delete": JobDeleted,
    "job_cleanup": JobCleanup,
    "job_read": JobRead,
    "job_write": JobWrite,
    "job_resize": JobResize,
    "job_wait": JobStatus,
    "job_cancel": JobStatus,
}
