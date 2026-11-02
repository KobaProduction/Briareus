"""Compatibility exports of independently attested current Platform membership."""

from authorization.application.project_membership import (
    VerifiedPlatformMembershipDelegation as VerifiedPlatformMembershipDelegation,
)
from authorization.infrastructure.project_membership import (
    PlatformCurrentProjectResolver as PlatformCurrentProjectResolver,
)
from authorization.infrastructure.project_membership import (
    TrustedPlatformDecisionPeer as TrustedPlatformDecisionPeer,
)
from authorization.infrastructure.project_membership import (
    VerifiedPlatformMembershipResponse as VerifiedPlatformMembershipResponse,
)
