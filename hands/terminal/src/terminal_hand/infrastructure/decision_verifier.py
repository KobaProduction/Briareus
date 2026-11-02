"""Pinned private JWT verifier; raw claims end at this codec boundary."""

from runtime_peer import PeerIdentity
from runtime_peer.effect_permit import decode_effect_permit
from service_runtime._authority_binding import _AuthorityBinding
from terminal_hand.domain.effect_decision import TerminalDecision


class JwtDecisionVerifier(_AuthorityBinding[PeerIdentity]):
    def verify(self, token: str) -> TerminalDecision:
        return TerminalDecision(
            decode_effect_permit(token, self._authority, "briareus:terminal-worker")
        )
