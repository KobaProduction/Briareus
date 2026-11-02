"""JSON grant boundary schemas shared by SQL and HTTP serializers."""

from authorization.application.session_receipts import ResourceGrantPayload as ResourceGrantPayload
from authorization.application.session_receipts import (
    ResourceSelectorPayload as ResourceSelectorPayload,
)
from authorization.domain.sessions import SessionResourceGrant


def resource_payload(scope: SessionResourceGrant) -> ResourceGrantPayload:
    return ResourceGrantPayload(
        hand=scope.hand,
        tool=scope.tool,
        action=scope.action,
        resource=ResourceSelectorPayload(kind=scope.resource_kind, id=scope.resource_id),
    )
