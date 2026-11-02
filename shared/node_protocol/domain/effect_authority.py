"""A permit binds one current request to one immutable execution placement."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class EffectBinding:
    node_uuid: UUID
    placement_uuid: UUID
    project_uuid: UUID
    workspace_uuid: UUID
    fingerprint: str
    module: str
    resource_id: str


@dataclass(frozen=True)
class EffectRequest:
    method: str
    tool: str | None
    arguments_digest: str
    body_digest: str
    bearer_digest: str


@dataclass(frozen=True)
class EffectAuthority:
    binding: EffectBinding
    request: EffectRequest
    issued_at: int
    expires_at: int

    def require_current(
        self,
        binding: EffectBinding,
        request: EffectRequest,
        bearer: str,
        now: int,
    ) -> None:
        if (
            self.binding != binding
            or self.request != request
            or not bearer.startswith("Bearer ")
            or bearer.count(" ") != 1
            or self.issued_at > now + 2
            or self.expires_at <= now
            or not 0 < self.expires_at - self.issued_at <= 5
        ):
            raise ValueError("Wrong or expired effect authority")
