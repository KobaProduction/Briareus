"""Compatibility exports for transport-bound private service attestation."""

from authorization.application.decision_transport import (
    TrustedPeerReplayGuard as TrustedPeerReplayGuard,
)
from authorization.domain.decision_transport import (
    VerifiedTransportPeerRequest as VerifiedTransportPeerRequest,
)
from authorization.presentation.decision_transport import (
    TransportAuthenticatedDecisionPeerResolver as TransportAuthenticatedDecisionPeerResolver,
)
