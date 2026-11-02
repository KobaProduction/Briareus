"""Control source-only R13 v1 signed current Project ownership/action decision.

Only Control SQL; membership, Project version, lifecycle and source revision
are freshly verified in one owner-local read transaction. OS/C2 activation
and runtime consumer wiring remain independent gates.
"""

from __future__ import annotations

from typing import TypeGuard

from common.owner_contracts import TrustedOwnerServicePeerPort as TrustedOwnerServicePeerPort
from common.owner_effect_authorization import (
    OwnerEffectDecisionSigner as OwnerEffectDecisionSigner,
)
from common.platform_db import PlatformDatabase as PlatformDatabase
from projects._control_proof_reader import _stored_revision
from projects._persistence import ProjectRow
from projects.control.infrastructure.current_authority import _ControlEffectDecision
from teams._persistence import TeamRow


def _project_current(project: ProjectRow | None) -> TypeGuard[ProjectRow]:
    return not (
        project is None
        or project.lifecycle_status != "active"
        or project.version < 1
        or (project.resource_revision < 0)
        or ((project.owner_user_id is None) == (project.owner_team_id is None))
    )


def _revoke_epoch(project: ProjectRow, team: TeamRow | None) -> int:
    return project.resource_revision + (
        team.version + team.resource_revision if team is not None else 0
    )


class ControlEffectIssuer(_ControlEffectDecision):
    _project_revision = staticmethod(_stored_revision)
    _team_revision = staticmethod(_stored_revision)
    _membership_revision = staticmethod(_stored_revision)
    _project_current = staticmethod(_project_current)
    _revoke_epoch = staticmethod(_revoke_epoch)
