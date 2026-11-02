"""Verify provider proof, effect binding and exclusive current lease."""

from typing import Protocol

from service_runtime._reference_bindings import _VerifierBinding
from terminal_hand.domain.effect_decision import EffectBinding, TerminalDecision


class DecisionVerifier(Protocol):
    def verify(self, token: str) -> TerminalDecision: ...


class VerifyTerminalDecision(_VerifierBinding[DecisionVerifier]):
    def execute(
        self, token: str, effect: EffectBinding, lease: tuple[str, str, int] | None
    ) -> TerminalDecision:
        decision = self._verifier.verify(token)
        decision.require_binding(effect)
        decision.require_lease(lease)
        return decision
