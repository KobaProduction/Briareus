"""Project native daemon observations into bounded domain readiness facts."""

from node_agent.domain.readiness import HealthStatus, ProcessState

from .container_models import InspectedState


def bounded_integer(value: int | None, minimum: int) -> int | None:
    return value if value is not None and minimum <= value <= 255 else None


def process_state(row: InspectedState) -> ProcessState:
    status: HealthStatus | None = None
    match row.health.status if row.health is not None else "none":
        case "starting":
            status = "starting"
        case "healthy":
            status = "healthy"
        case "unhealthy":
            status = "unhealthy"
        case "none":
            status = "none"
    return ProcessState(
        row.running,
        status,
        row.oom_killed,
        bounded_integer(row.exit_code, 0) if row.running is False else None,
        row.health.probe_exit_code if row.health is not None else None,
    )
