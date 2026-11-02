"""MVP control reserve, including the rootless Gateway helper."""

from .models import NodeBudget, ResourceLimits

CONTROLLER_LIMITS = ResourceLimits(memory_bytes=256 * 1024**2, cpu_millis=500, pids=128)
GATEWAY_LIMITS = ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=250, pids=64)


def validate_node_budget(budget: NodeBudget, ceiling: NodeBudget) -> None:
    """Core may allocate within the capacity explicitly provisioned by bootstrap."""
    rootless_budget(budget)
    if any(
        getattr(budget.total, key) > getattr(ceiling.total, key)
        for key in ResourceLimits.model_fields
    ):
        raise ValueError("Requested node budget exceeds provisioned capacity")


def rootless_budget(budget: NodeBudget) -> ResourceLimits:
    for key in ResourceLimits.model_fields:
        if getattr(budget.reserved, key) < getattr(CONTROLLER_LIMITS, key) + getattr(
            GATEWAY_LIMITS, key
        ):
            raise ValueError("Node reserve must cover both controller and Node Gateway")
    # Controller is in the outer engine; Gateway and workers share this slice.
    return ResourceLimits(
        **{
            key: getattr(budget.total, key) - getattr(CONTROLLER_LIMITS, key)
            for key in ResourceLimits.model_fields
        }
    )
