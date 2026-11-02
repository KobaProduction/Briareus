"""Closed audit facts from invalid-session protection."""

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, slots=True)
class InvalidSessionAttempt:
    count: int
    tool_name: str
    kind: Literal["invalid_session_attempt"] = field(default="invalid_session_attempt", init=False)


@dataclass(frozen=True, slots=True)
class OAuthSessionRevokedForAbuse:
    count: int
    kind: Literal["oauth_revoked_for_session_abuse"] = field(
        default="oauth_revoked_for_session_abuse", init=False
    )


type SessionAbuseEvent = InvalidSessionAttempt | OAuthSessionRevokedForAbuse
