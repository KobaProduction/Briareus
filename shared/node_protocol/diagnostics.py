"""Finite, safe operation failure facts; never provider logs or messages."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .domain.observations import FailureFacts


class FailureDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal[
        "queued", "pulling", "stopping", "creating", "checking", "rolling_back", "unknown"
    ]
    component: Literal["worker", "egress", "engine", "controller"]
    reason: Literal[
        "process_exited",
        "oom",
        "readiness_timeout",
        "unhealthy",
        "helper_unhealthy",
        "pull_failed",
        "unknown",
        "workspace_cleanup_uncertain",
        "workspace_initialization_failed",
        "workspace_identity_unverified",
        "network_policy_cleanup_uncertain",
        "network_policy_failed",
        "network_policy_unverified",
        "engine_unavailable",
        "engine_request_rejected",
        "rootless_unverified",
        "network_address_conflict",
    ]
    exit_code: int | None = Field(default=None, strict=True, ge=0, le=255)
    health_status: Literal["starting", "healthy", "unhealthy", "none"] | None = None
    oom_killed: bool | None = Field(default=None, strict=True)
    health_exit_code: int | None = Field(default=None, strict=True, ge=-1, le=255)


def diagnostic_facts(value: FailureDiagnostic) -> FailureFacts:
    return FailureFacts(
        value.stage,
        value.component,
        value.reason,
        value.exit_code,
        value.health_status,
        value.oom_killed,
        value.health_exit_code,
    )


def diagnostic_payload(value: FailureFacts) -> FailureDiagnostic:
    # Presence matters for the existing signed JSON digest: never add null keys.
    fields: dict[str, str | int | bool] = {
        "stage": value.stage,
        "component": value.component,
        "reason": value.reason,
    }
    for name, item in (
        ("exit_code", value.exit_code),
        ("health_status", value.health_status),
        ("oom_killed", value.oom_killed),
        ("health_exit_code", value.health_exit_code),
    ):
        if item is not None:
            fields[name] = item
    return FailureDiagnostic.model_validate(fields)
