"""Common CI job-log, incomplete-run retry and cancellation contracts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations


def log_tail(text: str, max_chars: int) -> tuple[str, bool]:
    return text[-max_chars:], len(text) > max_chars


class CIProvider(Protocol):
    def get_job_log(self, repository: str, job_id: int, max_chars: int, /) -> JsonObject: ...
    def retry_incomplete_run(self, repository: str, run_id: int, /) -> JsonObject: ...
    def cancel_run(self, repository: str, run_id: int, /) -> JsonObject: ...


@dataclass(frozen=True)
class CINames:
    job_log: str
    retry_incomplete: str
    cancel_run: str


def register_ci_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], CIProvider],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    provider: str,
    names: CINames,
) -> None:
    @mcp.tool(name=names.job_log, title=f"{provider} job log", annotations=read_annotations)
    def job_log(
        account_id: str,
        repository: str,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JsonObject:
        """Return the bounded tail of a CI job log."""
        return client_factory(account_id).get_job_log(repository, job_id, max_chars)

    @mcp.tool(
        name=names.retry_incomplete,
        title=f"{provider} retry incomplete jobs",
        annotations=write_annotations,
    )
    def retry_incomplete_run(account_id: str, repository: str, run_id: int) -> JsonObject:
        """Retry failed jobs in a run (including canceled jobs where supported by the provider)."""
        return client_factory(account_id).retry_incomplete_run(repository, run_id)

    @mcp.tool(
        name=names.cancel_run,
        title=f"{provider} cancel CI run",
        annotations=destructive_annotations,
    )
    def cancel_run(account_id: str, repository: str, run_id: int) -> JsonObject:
        """Cancel the explicit in-progress CI run/pipeline."""
        return client_factory(account_id).cancel_run(repository, run_id)
