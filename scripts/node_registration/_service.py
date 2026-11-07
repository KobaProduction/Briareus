from ._models import NodeResult, NodeRuntime, NodeSpec, RoleRegistry


def ensure_node(node: NodeSpec, registry: RoleRegistry) -> NodeResult:
    created = registry.ensure(node)
    return NodeResult(
        status="created" if created else "existing",
        node=node.node_id,
        origin=node.origin,
        runtime=NodeRuntime(required_role=node.node_id),
    )
