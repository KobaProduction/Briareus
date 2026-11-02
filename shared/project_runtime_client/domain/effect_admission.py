"""An owner effect belongs to the exact preflight action and project session."""

from dataclasses import dataclass

from .authorization import ProjectAction, ProjectInvocation, ProjectOperationScope
from .effect_protocol import _PHASES, EffectOwner, EffectPhase
from .effect_receipt import OwnerEffectUnavailable
from .revisions import valid_project_revision


@dataclass(frozen=True, slots=True)
class EffectAdmission:
    owner: EffectOwner
    phase: EffectPhase
    action: ProjectAction
    target_sha256: str
    expected_version: int

    def require_scope(self, invocation: ProjectInvocation) -> ProjectOperationScope:
        scope = invocation.operation_scope
        if scope is None:
            raise OwnerEffectUnavailable("OWNER_COMMAND_INVALID")
        if (
            scope.action != self.action
            or scope.project_id != invocation.project_id
            or scope.agent_session_uuid != invocation.session_uuid
            or self.owner not in _PHASES
            or self.phase not in _PHASES[self.owner]
            or not valid_project_revision(self.target_sha256)
            or type(self.expected_version) is not int
            or self.expected_version < 0
        ):
            raise OwnerEffectUnavailable("OWNER_COMMAND_INVALID")
        return scope
