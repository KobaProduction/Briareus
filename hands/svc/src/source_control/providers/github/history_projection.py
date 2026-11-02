from __future__ import annotations

from typing import Literal, overload

from .history_views import (
    ActorSource,
    CommitIdentity,
    CommitVerification,
    CommitVerificationMaterial,
    IdentitySource,
    VerificationSource,
)


def git_identity(item: IdentitySource | None, actor: ActorSource | None) -> CommitIdentity:
    return CommitIdentity(
        name=item.name or "" if item else "",
        email=item.email or "" if item else "",
        date=item.date or "" if item else "",
        login=actor.login or None if actor else None,
        id=actor.id if actor else None,
        type=actor.type or None if actor else None,
    )


@overload
def verification(
    item: VerificationSource | None, *, include_material: Literal[True]
) -> CommitVerificationMaterial: ...


@overload
def verification(
    item: VerificationSource | None, *, include_material: Literal[False]
) -> CommitVerification: ...


def verification(
    item: VerificationSource | None, *, include_material: bool
) -> CommitVerification | CommitVerificationMaterial:
    data = item or VerificationSource()
    summary = CommitVerification(
        verified=bool(data.verified),
        reason=data.reason or "",
        verified_at=data.verified_at,
        signature_present=bool(data.signature),
        payload_present=bool(data.payload),
    )
    if include_material:
        return CommitVerificationMaterial(
            verified=summary.verified,
            reason=summary.reason,
            verified_at=summary.verified_at,
            signature_present=summary.signature_present,
            payload_present=summary.payload_present,
            signature=data.signature,
            payload=data.payload,
        )
    return summary
