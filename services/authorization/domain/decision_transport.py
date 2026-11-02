"""Request-bound authenticated peer facts and single-use nonce invariants."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from authorization.domain.action_audiences import ALLOWED_AUDIENCES
from authorization.domain.decision_identity import VerifiedDecisionPeer
from authorization.domain.decisions import DecisionScopeDenied

_NONCE = re.compile(r"[a-f0-9]{32,64}\Z", re.ASCII)
_SHA256 = re.compile(r"[a-f0-9]{64}\Z", re.ASCII)
_NONCE_AUDIENCES = frozenset(
    {"gateway", "files", "terminal", "web", "svc", "reverse", "infrastructure"}
)


@dataclass(frozen=True, slots=True)
class ReplayNonce:
    source_audience: str
    nonce: str
    body_sha256: str

    @classmethod
    def checked(cls, source: object, nonce: object, digest: object) -> ReplayNonce | None:
        if not isinstance(source, str) or source not in _NONCE_AUDIENCES:
            return None
        if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
            return None
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            return None
        return cls(source, nonce, digest)

    def storage_key(self) -> str:
        digest = hashlib.sha256(f"{self.source_audience}:{self.nonce}".encode("ascii")).hexdigest()
        return f"briareus:access:verified-peer:v1:{digest}"


@dataclass(frozen=True, slots=True)
class VerifiedTransportPeerRequest:
    transport: Literal["mtls", "unix-peer"]
    consumer: Literal["gateway", "hand"]
    source_audience: str
    target_audience: Literal["briareus:access"]
    http_body_sha256: str
    resolved_effect_key: str | None
    nonce: str
    authenticated_at: datetime
    expires_at: datetime
    verified_peer: bool

    def verify_scope(self, now: datetime) -> None:
        self._verify_identity()
        self._verify_window(now)
        if _SHA256.fullmatch(self.http_body_sha256) is None or _NONCE.fullmatch(self.nonce) is None:
            raise DecisionScopeDenied("private service peer scope or freshness denied")
        if self.consumer == "hand":
            self._verify_effect()

    def _verify_identity(self) -> None:
        if not self.verified_peer or self.transport not in {"mtls", "unix-peer"}:
            raise DecisionScopeDenied("private service peer scope or freshness denied")
        if (
            self.source_audience not in ALLOWED_AUDIENCES
            or self.target_audience != "briareus:access"
        ):
            raise DecisionScopeDenied("private service peer scope or freshness denied")
        if self.consumer == "gateway":
            if self.source_audience != "gateway" or self.resolved_effect_key is not None:
                raise DecisionScopeDenied("private service peer scope or freshness denied")
        elif self.source_audience == "gateway" or not self.resolved_effect_key:
            raise DecisionScopeDenied("private service peer scope or freshness denied")

    def _verify_window(self, now: datetime) -> None:
        if self.authenticated_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise DecisionScopeDenied("private service peer scope or freshness denied")
        if not now - timedelta(seconds=15) <= self.authenticated_at <= now + timedelta(seconds=2):
            raise DecisionScopeDenied("private service peer scope or freshness denied")
        if not now < self.expires_at <= self.authenticated_at + timedelta(seconds=15):
            raise DecisionScopeDenied("private service peer scope or freshness denied")

    def _verify_effect(self) -> None:
        try:
            effect: object = json.loads(self.resolved_effect_key or "")
        except (ValueError, TypeError):
            raise DecisionScopeDenied("invalid private Hand effect selector") from None
        if not isinstance(effect, list) or len(effect) != 4:
            raise DecisionScopeDenied("authenticated Hand does not own effect")
        if any(not isinstance(value, str) for value in effect) or effect[0] != self.source_audience:
            raise DecisionScopeDenied("authenticated Hand does not own effect")
        if self.resolved_effect_key != json.dumps(effect, ensure_ascii=True, separators=(",", ":")):
            raise DecisionScopeDenied("authenticated Hand does not own effect")

    def verify_body(self, body: bytes) -> None:
        if not 1 <= len(body) <= 8192 or hashlib.sha256(body).hexdigest() != self.http_body_sha256:
            raise DecisionScopeDenied("peer proof is not bound to actual request body")

    def decision_peer(self) -> VerifiedDecisionPeer:
        return VerifiedDecisionPeer(
            self.consumer,
            self.source_audience,
            self.target_audience,
            self.expires_at,
            self.resolved_effect_key,
        )
