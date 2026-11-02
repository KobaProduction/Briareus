"""Dispatch only a current effect and discard expired foreground outcomes."""

from dataclasses import dataclass
from typing import Protocol

from serena_hand.domain.effects import EffectAuthority


class Clock(Protocol):
    def now(self) -> float: ...


class EffectOperation[Result](Protocol):
    async def execute(self) -> Result: ...


@dataclass(frozen=True)
class DispatchEffect:
    clock: Clock
    tools: frozenset[str]

    async def execute[Result](
        self,
        authority: EffectAuthority,
        operation: EffectOperation[Result],
    ) -> Result:
        authority.require_current(self.clock.now(), self.tools)
        result = await operation.execute()
        authority.require_outcome_current(self.clock.now())
        return result
