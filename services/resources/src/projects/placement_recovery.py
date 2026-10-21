"""Project a retained prior deployment only from a fresh authenticated Node inventory."""
from node_protocol import Deployment


def current_spec(placement, operation):
    # A failed desired update remains in its immutable operation history.
    # A ready restored placement is described by its actual prior deployment.
    restored = (placement.state == "ready" and operation.phase == "failed"
                and operation.error_code == "UPDATE_FAILED" and operation.previous is not None)
    return Deployment.model_validate(operation.previous if restored else operation.desired)


def verified_restoration(placement, operation, receipt, inventory, *, node):
    if (receipt.get("phase") != "failed" or receipt.get("error") != "UPDATE_FAILED"
        or operation.previous is None or placement.applied_release_uuid is None
        or not isinstance(inventory, dict) or inventory.get("enabled") is not True
        or inventory.get("node_uuid") != str(operation.node_uuid)
        or node is None or node.id != operation.node_uuid or not node.enabled or node.deleted_at is not None
        or inventory.get("sequence") != node.sequence):
        return None
    previous = Deployment.model_validate(operation.previous)
    if (previous.id != placement.id or previous.node_uuid != operation.node_uuid
        or previous.node_uuid != placement.node_uuid or previous.project_uuid != placement.project_uuid
        or previous.release.module != placement.artifact_key or not previous.enabled
        or previous.workspace is None or previous.workspace.id != placement.storage_uuid):
        return None
    items = inventory.get("items")
    if not isinstance(items, list):
        return None
    own = [item for item in items if isinstance(item,dict) and item.get("placement_uuid") == str(placement.id)]
    if (len(own) != 1 or own[0].get("running") is not True or own[0].get("ready") is not True
        or own[0].get("fingerprint") != previous.fingerprint
        or own[0].get("limits") != previous.limits.model_dump(mode="json")):
        return None
    return previous
