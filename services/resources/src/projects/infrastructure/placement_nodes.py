"""Adapt persisted node facts to the shared scope and availability admission rule."""

from projects._node_persistence import NodeRow
from projects.domain.node_administration import NodeActor, NodeConflict, NodeForbidden
from projects.domain.placement_admission import PlacementNode


def qualified_placement_node(
    row: NodeRow | None,
    actor: NodeActor,
    *,
    scope_detail: str = "Node must belong to the current project scope",
) -> NodeRow:
    if row is None:
        raise NodeConflict("An enabled paired node is required")
    node = PlacementNode(
        row.scope, row.owner_uuid, row.enabled, row.deleted_at is not None, bool(row.public_key)
    )
    node.require_available()
    try:
        node.require_project_scope(actor)
    except NodeForbidden:
        raise NodeForbidden(scope_detail) from None
    return row
