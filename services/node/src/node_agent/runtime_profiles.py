"""Fixed execution profiles; callers never supply Docker flags or host paths."""

from node_protocol import Deployment

SUPERVISOR_MODULES = frozenset({"terminal", "web", "svc", "infrastructure", "reverse", "serena"})
EGRESS_MODULES = frozenset({"files", "web", "svc", "infrastructure"})
EGRESS_MEMORY = 64 * 1024**2
EGRESS_CPU = 100
EGRESS_PIDS = 32
ROLE_LABEL = "io.briareus.role"
EGRESS_REQUIRED = "io.briareus.requires-egress"


def uses_egress(spec: Deployment) -> bool:
    if spec.release.module == "files":
        # The original immutable read-only Files release predates networked
        # ingest. Preserve its rollback contract and existing resource budget.
        return (
            spec.limits.cpu_millis >= 200
            and spec.limits.pids >= 64
            and spec.limits.memory_bytes >= 128 * 1024**2
        )
    return spec.release.module in EGRESS_MODULES


def uses_direct_network(spec: Deployment) -> bool:
    return (
        spec.release.module == "terminal"
        and spec.configuration is not None
        and spec.configuration.network is not None
        and spec.configuration.network.profile == "public"
    )
