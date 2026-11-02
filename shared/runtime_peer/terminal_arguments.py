"""Wire arguments of the existing Terminal catalogue; omission stays distinct from null."""

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt
from pydantic_core import MISSING


class TerminalArgumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class TerminalInspectionArguments(TerminalArgumentRecord):
    """terminal_status and workspace_list have no argument fields."""


class WorkspaceArguments(TerminalArgumentRecord):
    workspace_id: str


class WorkspaceDeleteArguments(WorkspaceArguments):
    force: bool | MISSING = MISSING


class TerminalExecutionArguments(WorkspaceArguments):
    command: str
    cwd: str | MISSING = MISSING
    env: dict[str, str] | MISSING | None = MISSING
    timeout_seconds: StrictInt | StrictFloat | MISSING | None = MISSING
    max_output_bytes: int | MISSING | None = MISSING

    def observation_timeout(self) -> int | float | None:
        return None if self.timeout_seconds is MISSING else self.timeout_seconds


class JobStartArguments(WorkspaceArguments):
    command: str
    cwd: str | MISSING = MISSING
    env: dict[str, str] | MISSING | None = MISSING
    interactive: bool | MISSING = MISSING
    label: str | MISSING = MISSING
    cols: int | MISSING = MISSING
    rows: int | MISSING = MISSING
    timeout_seconds: StrictInt | StrictFloat | MISSING | None = MISSING


class JobArguments(TerminalArgumentRecord):
    job_id: str


class JobListArguments(TerminalArgumentRecord):
    workspace_id: str | MISSING = MISSING
    state: str | MISSING = MISSING
    offset: int | MISSING = MISSING
    limit: int | MISSING = MISSING


class JobCleanupArguments(TerminalArgumentRecord):
    older_than_hours: int | MISSING = MISSING
    dry_run: bool | MISSING = MISSING
    limit: int | MISSING = MISSING


class JobReadArguments(JobArguments):
    cursor: int | MISSING = MISSING
    max_bytes: int | MISSING | None = MISSING
    wait_seconds: StrictInt | StrictFloat | MISSING = MISSING


class JobWriteArguments(JobArguments):
    data: str


class JobResizeArguments(JobArguments):
    cols: int
    rows: int


class JobWaitArguments(JobArguments):
    timeout_seconds: StrictInt | StrictFloat | MISSING = MISSING


class JobCancelArguments(JobArguments):
    grace_seconds: StrictInt | StrictFloat | MISSING = Field(default=MISSING, gt=0, le=3)


type TerminalArguments = (
    TerminalExecutionArguments
    | WorkspaceDeleteArguments
    | WorkspaceArguments
    | JobStartArguments
    | JobReadArguments
    | JobWriteArguments
    | JobResizeArguments
    | JobWaitArguments
    | JobCancelArguments
    | JobArguments
    | JobListArguments
    | JobCleanupArguments
    | TerminalInspectionArguments
)

TERMINAL_ARGUMENTS: dict[str, type[TerminalArguments]] = {
    "terminal_status": TerminalInspectionArguments,
    "workspace_list": TerminalInspectionArguments,
    "workspace_create": WorkspaceArguments,
    "workspace_info": WorkspaceArguments,
    "workspace_delete": WorkspaceDeleteArguments,
    "terminal_exec": TerminalExecutionArguments,
    "job_start": JobStartArguments,
    "job_status": JobArguments,
    "job_list": JobListArguments,
    "job_delete": JobArguments,
    "job_cleanup": JobCleanupArguments,
    "job_read": JobReadArguments,
    "job_write": JobWriteArguments,
    "job_resize": JobResizeArguments,
    "job_wait": JobWaitArguments,
    "job_cancel": JobCancelArguments,
}
