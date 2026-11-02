from owner_protocol.proofs import CurrentOwnerAuthorityPort as CurrentOwnerAuthorityPort
from owner_protocol.proofs import OwnerAuthorityUnavailable as OwnerAuthorityUnavailable
from owner_protocol.proofs import OwnerCommandDTO as OwnerCommandDTO
from owner_protocol.proofs import OwnerProofClaims as OwnerProofClaims
from owner_protocol.proofs import OwnerProofDatabaseNames as OwnerProofDatabaseNames
from owner_protocol.proofs import RequiredAuthority as RequiredAuthority
from owner_protocol.proofs import SignedOwnerProofs as SignedOwnerProofs
from owner_protocol.proofs import TrustedOwnerPin as TrustedOwnerPin
from owner_protocol.proofs import TrustedOwnerServicePeerPort as TrustedOwnerServicePeerPort
from owner_protocol.proofs import VerifiedOwnerOperation as VerifiedOwnerOperation
from owner_protocol.proofs import VerifiedOwnerServicePeer as VerifiedOwnerServicePeer
from owner_protocol.proofs import _CompositionOwnerProofAuthority as _OwnerProofAuthority
from owner_protocol.proofs import require_online_owner_decision as require_online_owner_decision
from owner_protocol.proofs import require_signed_payload as require_signed_payload

from .domain.owner_authority import OWNER_DB_NAMES as OWNER_DB_NAMES


class OwnerProofAuthority(_OwnerProofAuthority):
    """Keep this root's authority type and current database-name lookup."""

    _owner_database_lookup = staticmethod(OWNER_DB_NAMES.__getitem__)
