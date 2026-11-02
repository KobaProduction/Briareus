"""Bind human Terminal effects to supervisor-owned job records."""

from dataclasses import dataclass

from mcp.types import CallToolRequestParams, CallToolResult
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import MISSING

from terminal_hand.domain.human_principal import HumanOperationPrincipal
from terminal_hand.infrastructure.human_job_owners import HumanJobOwners
from terminal_hand.infrastructure.worker_messages import (
    MAX_PRIVATE_WORKER_BYTES,
    HumanJobScope,
    PrivateWorkerCommand,
    TerminalReply,
)

_CREATES = frozenset({"job_start", "terminal_exec"})
_POINTS = frozenset(
    {"job_status", "job_read", "job_wait", "job_cancel", "job_write", "job_resize", "job_delete"}
)
_BULK = frozenset({"job_list", "job_cleanup"})


class _JobReference(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class _JobListing(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    jobs: tuple[_JobReference, ...] = Field(max_length=1000)


class _JobCleanup(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    job_ids: tuple[str, ...] = Field(max_length=1000)


@dataclass(frozen=True, slots=True)
class HumanJobExecution:
    owners: HumanJobOwners
    principal: HumanOperationPrincipal
    call: CallToolRequestParams
    fingerprint: str

    def request(self) -> bytes:
        creation = None
        if self.call.name in _CREATES:
            creation = self.owners.bind(self.principal, self.fingerprint)
        if self.call.name in _POINTS:
            selected = _JobReference.model_validate(self.call.arguments)
            self.owners.require(self.principal, selected.job_id)
        scope = HumanJobScope(
            namespace=self.principal.namespace,
            creation_id=creation,
            allowed_jobs=self.owners.allowed(self.principal) if self.call.name in _BULK else None,
        )
        command = PrivateWorkerCommand(
            id=self.principal.operation_uuid, call=self.call, human=scope
        )
        wire = command.wire_json(exclude_none=True, sort_keys=True, compact=True).encode("ascii")
        if len(wire) + 1 > MAX_PRIVATE_WORKER_BYTES:
            raise ValueError("Human job scope exceeds private transport budget")
        return wire

    def validate(self, reply: TerminalReply) -> None:
        if reply.error is not MISSING or not isinstance(reply.result, CallToolResult):
            return
        if reply.result.is_error:
            return
        value = reply.result.structured_content
        tool = self.call.name
        if tool in _CREATES:
            created = _JobReference.model_validate(value)
            if created.job_id != self.principal.operation_uuid.hex:
                raise ValueError("Unconfirmed human job creation identity")
            self.owners.require(self.principal, created.job_id)
        elif tool in _POINTS:
            selected = _JobReference.model_validate(self.call.arguments)
            returned = _JobReference.model_validate(value)
            if returned.job_id != selected.job_id:
                raise ValueError("Job outcome target changed")
            self.owners.require(self.principal, returned.job_id)
        elif tool == "job_list":
            for item in _JobListing.model_validate(value).jobs:
                self.owners.require(self.principal, item.job_id)
        elif tool == "job_cleanup":
            for job_id in _JobCleanup.model_validate(value).job_ids:
                self.owners.require(self.principal, job_id)
