"""Typed saved facts and non-authoritative recovery for retained Terminal jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
)

from .job_contract import JobState


@dataclass(frozen=True, slots=True)
class SavedJobMetadata:
    job_id: str
    workspace_id: str
    command: str
    cwd: str
    interactive: bool
    label: str
    state: str
    created_at: float
    started_at: float
    ended_at: float | None
    exit_code: int | None
    signal_number: int | None
    pid: int | None
    log_path: str
    log_truncated: bool
    timeout_seconds: float | None

    @classmethod
    def from_job(cls, job: JobState) -> SavedJobMetadata:
        return cls(
            job_id=job.job_id,
            workspace_id=job.workspace_id,
            command=job.command,
            cwd=job.cwd,
            interactive=job.interactive,
            label=job.label,
            state=job.state,
            created_at=job.created_at,
            started_at=job.started_at,
            ended_at=job.ended_at,
            exit_code=job.exit_code,
            signal_number=job.signal_number,
            pid=job.pid,
            log_path=str(job.log_path),
            log_truncated=job.log_truncated,
            timeout_seconds=job.timeout_seconds,
        )


class _RecoverySelection(BaseModel):
    """Select conditional fields with the original state and truthiness rules."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    state: Annotated[str, BeforeValidator(str)] = "unknown"
    has_timeout: Annotated[bool, BeforeValidator(bool)] = Field(
        default=False, validation_alias="timeout_seconds"
    )


class _RecoveryFacts(BaseModel):
    """Saved PID/path are deliberately absent: recovery cannot confer OS authority."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=True)

    job_id: StrictStr
    workspace_id: Annotated[str, BeforeValidator(str)]
    command: Annotated[str, BeforeValidator(str)] = ""
    cwd: Annotated[str, BeforeValidator(str)] = ""
    interactive: Annotated[bool, BeforeValidator(bool)] = False
    label: Annotated[str, BeforeValidator(str)] = ""
    state: Annotated[str, BeforeValidator(str)] = "unknown"
    created_at: Annotated[float, BeforeValidator(float)] = 0.0
    started_at: Annotated[float, BeforeValidator(float)] = 0.0
    exit_code: StrictInt | None = None
    signal_number: StrictInt | None = None
    log_truncated: Annotated[bool, BeforeValidator(bool)] = False


class _FinishedFacts(_RecoveryFacts):
    ended_at: Annotated[float, BeforeValidator(float)] | None = None


class _TimedFacts(_RecoveryFacts):
    timeout_seconds: Annotated[float, BeforeValidator(float)]


class _FinishedTimedFacts(_FinishedFacts):
    timeout_seconds: Annotated[float, BeforeValidator(float)]


@dataclass(frozen=True, slots=True)
class RecoveredJobMetadata:
    job_id: str
    workspace_id: str
    command: str
    cwd: str
    interactive: bool
    label: str
    state: str
    created_at: float
    started_at: float
    ended_at: float | None
    exit_code: int | None
    signal_number: int | None
    log_truncated: bool
    timeout_seconds: float

    @classmethod
    def decode(cls, raw: str) -> RecoveredJobMetadata:
        selection = _RecoverySelection.model_validate_json(raw)
        facts: _RecoveryFacts
        ended_at: float | None = None
        if selection.state in {"running", "cancelling"}:
            facts = (
                _TimedFacts.model_validate_json(raw)
                if selection.has_timeout
                else _RecoveryFacts.model_validate_json(raw)
            )
        else:
            finished = (
                _FinishedTimedFacts.model_validate_json(raw)
                if selection.has_timeout
                else _FinishedFacts.model_validate_json(raw)
            )
            facts = finished
            ended_at = finished.ended_at
        timeout = (
            facts.timeout_seconds if isinstance(facts, (_TimedFacts, _FinishedTimedFacts)) else 0.0
        )
        return cls(
            job_id=facts.job_id,
            workspace_id=facts.workspace_id,
            command=facts.command,
            cwd=facts.cwd,
            interactive=facts.interactive,
            label=facts.label,
            state=facts.state,
            created_at=facts.created_at,
            started_at=facts.started_at,
            ended_at=ended_at,
            exit_code=facts.exit_code,
            signal_number=facts.signal_number,
            log_truncated=facts.log_truncated,
            timeout_seconds=timeout,
        )
