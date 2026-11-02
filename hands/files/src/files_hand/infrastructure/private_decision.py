"""Pinned private JWT verifier; raw claims end at this codec boundary."""

from files_hand.domain.private_effect import PrivateFilesDecision
from runtime_peer import PeerIdentity
from runtime_peer.effect_permit import decode_effect_permit
from service_runtime._authority_binding import _AuthorityBinding


class JwtDecisionVerifier(_AuthorityBinding[PeerIdentity]):
    def verify(self, token: str) -> PrivateFilesDecision:
        return PrivateFilesDecision(decode_effect_permit(token, self._authority, "briareus:files"))
