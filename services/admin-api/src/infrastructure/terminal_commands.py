"""Concrete requests to the private Terminal MCP service."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class JobSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str


class ReadJob(JobSelection):
    cursor: int
    max_bytes: int
    wait_seconds: Literal[0] = 0


class CancelJob(JobSelection):
    grace_seconds: Literal[2] = 2


class CleanupJobs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    older_than_hours: int
    dry_run: bool
    limit: Literal[1000] = 1000


class DeleteWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workspace_id: str
    force: Literal[False] = False
