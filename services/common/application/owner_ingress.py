"""Fresh, bounded verification of the ingress protecting one owner."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from common.domain.owner_runtime import OwnerName, VerifiedOwnerIngress


class OwnerIngressVerifier(Protocol):
    async def verify_running_ingress(self) -> VerifiedOwnerIngress | None: ...


@dataclass(frozen=True, slots=True)
class AttestOwnerIngress:
    owner: OwnerName
    verifier: OwnerIngressVerifier | None
    now: Callable[[], datetime]

    async def execute(self) -> bool:
        if self.verifier is None:
            return False
        try:
            async with asyncio.timeout(3):
                verified = await self.verifier.verify_running_ingress()
            return isinstance(verified, VerifiedOwnerIngress) and verified.authorizes(
                self.owner, self.now()
            )
        except Exception:
            return False
