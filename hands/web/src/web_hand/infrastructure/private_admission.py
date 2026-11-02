"""Verify the signed wire decision and fingerprint the original browser arguments."""

import hashlib

from runtime_peer import PeerIdentity, canonical_json
from runtime_peer.effect_permit import decode_effect_permit
from web_hand.domain.private_effect import BrowserEffectTarget, PrivateBrowserOperation
from web_hand.presentation.private_call import BrowserCall


class PrivateBrowserAdmission:
    def __init__(self, authority: PeerIdentity, target: BrowserEffectTarget) -> None:
        self._authority = authority
        self._target = target

    def authorize(self, command: BrowserCall) -> PrivateBrowserOperation:
        facts = decode_effect_permit(command.permit, self._authority, "briareus:web")
        self._target.require_effect(
            facts,
            command.call.name,
            hashlib.sha256(canonical_json(command.call.arguments or {})).hexdigest(),
        )
        fingerprint = hashlib.sha256(
            canonical_json(
                {
                    "actor": str(facts.actor_uuid),
                    "session": str(facts.session_uuid),
                    "tool": command.call.name,
                    "arguments": command.call.arguments or {},
                }
            )
        ).hexdigest()
        return PrivateBrowserOperation(
            facts.operation_uuid, fingerprint, command.open_url(), facts.expires_at
        )
