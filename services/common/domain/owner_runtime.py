"""Trust facts and local diagnostic visibility for private persistence owners."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime

from common.domain.owner_authority import OwnerName as OwnerName


@dataclass(frozen=True, slots=True)
class VerifiedOwnerIngress:
    owner: OwnerName
    authenticated_transport: str
    signer_present: bool
    expires_at: datetime

    def authorizes(self, owner: OwnerName, now: datetime) -> bool:
        return (
            self.owner == owner
            and self.authenticated_transport in {"mtls", "unix-peer"}
            and self.signer_present
            and self.expires_at.tzinfo is not None
            and self.expires_at > now
        )


def permits_local_schema_status(*, origin: str, server_host: str, forwarded: bool) -> bool:
    """Both socket ends must be loopback; proxy claims confer no authority."""
    if forwarded:
        return False
    try:
        return (
            ipaddress.ip_address(origin).is_loopback
            and ipaddress.ip_address(server_host).is_loopback
        )
    except ValueError:
        return False
