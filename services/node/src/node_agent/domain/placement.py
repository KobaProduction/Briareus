"""A replacement cannot relocate project authority or workspace ownership."""

from uuid import UUID

TERMINAL_PHASES = frozenset({"succeeded", "failed"})


class OperationConflict(RuntimeError):
    """The operation conflicts with current placement or journal authority."""


def validate_placement_owner(
    previous_project: UUID,
    desired_project: UUID,
    previous_workspace: UUID | None,
    desired_workspace: UUID | None,
) -> None:
    if previous_project != desired_project:
        raise OperationConflict("A placement cannot change project ownership")
    if previous_workspace != desired_workspace:
        raise OperationConflict("Storage relocation requires a separate placement operation")
