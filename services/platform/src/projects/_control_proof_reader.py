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
from projects._current_state import membership_state, project_state, team_state
from projects.control.actor_contracts import TrustedControlActorSource as TrustedControlActorSource
from projects.control.actor_contracts import VerifiedControlActor as VerifiedControlActor
from projects.control.infrastructure.current_authority import _ControlProjectProof


class ControlOwnerProofReader(_ControlProjectProof):
    _project_revision = staticmethod(project_state)
    _team_revision = staticmethod(team_state)
    _membership_revision = staticmethod(membership_state)
