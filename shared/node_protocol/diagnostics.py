"""Finite, safe operation failure facts; never provider logs or messages."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class FailureDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage: Literal["queued", "pulling", "stopping", "creating", "checking", "rolling_back", "unknown"]
    component: Literal["worker", "egress", "engine", "controller"]
    reason: Literal["process_exited", "oom", "readiness_timeout", "unhealthy", "helper_unhealthy", "pull_failed", "unknown",
        "workspace_cleanup_uncertain", "workspace_initialization_failed", "workspace_identity_unverified",
        "network_policy_cleanup_uncertain", "network_policy_failed", "network_policy_unverified",
        "engine_unavailable", "engine_request_rejected", "rootless_unverified", "network_address_conflict"]
    exit_code: int | None = Field(default=None, strict=True, ge=0, le=255)
    health_status: Literal["starting", "healthy", "unhealthy", "none"] | None = None
    oom_killed: bool | None = Field(default=None, strict=True)
    health_exit_code: int | None = Field(default=None, strict=True, ge=-1, le=255)


def diagnostic_wire(value):
    return FailureDiagnostic.model_validate(value).model_dump(mode="json", exclude_none=True)
