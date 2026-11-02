"""Exact deployed effect-scope wire shape shared by browser and owner adapters."""

from control_panel_api.domain.approval_policy import EffectScope
from runtime_peer.access_management_wire import EffectScopeWire
from runtime_peer.access_management_wire import ResourceScopeWire as ResourceScopePayload


class ScopedEffectPayload(EffectScopeWire):
    resource: ResourceScopePayload

    def scope(self) -> EffectScope:
        return EffectScope(self.hand, self.tool, self.action, self.resource.kind, self.resource.id)

    @classmethod
    def from_scope(cls, scope: EffectScope) -> "ScopedEffectPayload":
        return cls(
            hand=scope.hand,
            tool=scope.tool,
            action=scope.action,
            resource=ResourceScopePayload(kind=scope.resource_kind, id=scope.resource_id),
        )
