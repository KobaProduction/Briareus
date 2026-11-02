"""Current Control Project/Team membership decision from ONLY briareus_platform.

The caller's User role and credential revision must already be attested by an
independent current Identity issuer. No JWT/Project ID alone grants resources.
This source is not mounted until independently accepted mTLS/Unix C1-B2/C2.
"""

from __future__ import annotations

from dataclasses import dataclass as dataclass
from typing import Protocol as Protocol

from common.owner_contracts import (
    TrustedOwnerServicePeerPort as TrustedOwnerServicePeerPort,
)
from common.owner_contracts import (
    VerifiedOwnerServicePeer as VerifiedOwnerServicePeer,
)
from common.owner_proof_signing import SourceOwnerSigner as SourceOwnerSigner
from common.platform_db import PlatformDatabase as PlatformDatabase
from projects._persistence import ProjectRow
from projects.control.actor_contracts import TrustedControlActorSource as TrustedControlActorSource
from projects.control.actor_contracts import VerifiedControlActor as VerifiedControlActor
from projects.control.infrastructure.current_authority import _ControlProjectProof
from teams._persistence import TeamMembershipRow, TeamRow


def _stored_revision(row: ProjectRow | TeamRow | TeamMembershipRow) -> int:
    return row.version


class ControlOwnerProofReader(_ControlProjectProof):
    _project_revision = staticmethod(_stored_revision)
    _team_revision = staticmethod(_stored_revision)
    _membership_revision = staticmethod(_stored_revision)
