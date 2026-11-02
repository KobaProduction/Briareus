"""Only a running healthy main and its complete placement are ready."""

from dataclasses import dataclass
from typing import Literal

HealthStatus = Literal["starting", "healthy", "unhealthy", "none"]


@dataclass(frozen=True, slots=True)
class ProcessState:
    running: bool | None
    health: HealthStatus | None
    oom_killed: bool | None
    exit_code: int | None
    probe_exit_code: int | None

    @property
    def failed(self) -> bool:
        return not self.running or self.health == "unhealthy"

    def failure_reason(self, *, helper: bool, timed_out: bool) -> str:
        if self.oom_killed is True:
            return "oom"
        if self.running is False:
            return "process_exited"
        if self.health == "unhealthy":
            return "helper_unhealthy" if helper else "unhealthy"
        return "readiness_timeout" if timed_out else "unknown"
