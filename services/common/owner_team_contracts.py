"""Team-only signed owner decisions: Team IDs are never fake Project IDs.

No public route, stored team bearer or implicit global Project context.
Physical issuer/peer sources remain C1-B2/C2 gated and fail closed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from common.owner_contracts import OwnerAuthorityUnavailable, TrustedOwnerPin
from common.platform_db import OWNER_DB_NAMES
from owner_protocol.commands import _idempotency_key

RequiredAuthority = Literal["identity", "platform", "access"]


@dataclass(frozen=True, slots=True)
class TeamMemberPayload:
    """Exact signed membership parameters; target validation remains at the owner."""

    target_user_id: str


@dataclass(frozen=True, slots=True)
class TeamOwnerTransferPayload:
    """Exact signed transfer parameters, including explicit confirmation."""

    target_user_id: str
    confirmed: bool


class TeamOwnerCommandDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    operation_uuid: UUID
    team_id: UUID
    caller_user_id: UUID
    operation: Literal["team.member.add", "team.member.remove", "team.owner.transfer"]
    idempotency_key: str = Field(min_length=1, max_length=128)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_identity_revision: int = Field(ge=1)
    expected_team_revision: int = Field(ge=1)
    expected_access_revision: int = Field(ge=1)

    _original_key = field_validator("idempotency_key")(staticmethod(_idempotency_key))

    @field_validator("operation_uuid", "team_id", "caller_user_id")
    @classmethod
    def _v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("Team scope and actor IDs must be distinct UUIDv4 values")
        return value


class SignedTeamProofs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: SecretStr
    platform: SecretStr
    access: SecretStr


class TeamOwnerProofClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    iss: str
    aud: str
    sub: str
    owner: RequiredAuthority
    owner_database: str
    operation_uuid: UUID
    team_id: UUID
    caller_user_id: UUID
    operation: str
    idempotency_key: str
    payload_sha256: str
    active: bool
    role: Literal["user", "superuser"] | None = None
    capabilities: tuple[str, ...] = ()
    owner_revision: int = Field(ge=1)
    authority_epoch: UUID
    iat: int
    nbf: int
    exp: int


class IdentityTargetProofClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    iss: str
    aud: str
    sub: str
    owner: Literal["identity"]
    owner_database: Literal["briareus_identity"]
    operation_uuid: UUID
    team_id: UUID
    target_user_id: UUID
    enabled: bool
    credential_version: int = Field(ge=1)
    iat: int
    nbf: int
    exp: int


@dataclass(frozen=True, slots=True)
class VerifiedTeamOperation:
    request: TeamOwnerCommandDTO
    actor_role: Literal["user", "superuser"]
    identity_epoch: UUID
    team_epoch: UUID
    access_epoch: UUID
    verified_at: datetime


class CurrentTeamOwnerPort(Protocol):
    async def fetch_current(self, command: TeamOwnerCommandDTO) -> SignedTeamProofs: ...

    async def fetch_target_identity(
        self, command: TeamOwnerCommandDTO, target_user_id: UUID
    ) -> SecretStr:
        """Return fresh Identity-signed target status, not a target-user UUID."""
        ...


class TeamOwnerProofAuthority:
    def __init__(self, pins: tuple[TrustedOwnerPin, ...]) -> None:
        if len(pins) != 3 or {pin.owner for pin in pins} != {"identity", "platform", "access"}:
            raise ValueError("Team operations require all three fixed owner keys")
        if any(not pin.issuer or not pin.kid or not pin.public_key_pem for pin in pins):
            raise ValueError("invalid independently pinned source-owner key")
        self._pins = {pin.owner: pin for pin in pins}
        self._audience = "briareus:platform"

    @staticmethod
    def _decode[T: BaseModel](token: SecretStr, pin: TrustedOwnerPin, claims_type: type[T]) -> T:
        try:
            raw = token.get_secret_value()
            header = jwt.get_unverified_header(raw)
            if (
                header.get("alg") != "EdDSA"
                or header.get("kid") != pin.kid
                or header.get("crit")
                or header.get("typ") not in {"JWT", None}
            ):
                raise OwnerAuthorityUnavailable("Team authority signer key mismatch")
            result = jwt.decode(
                raw,
                pin.public_key_pem,
                algorithms=["EdDSA"],
                issuer=pin.issuer,
                audience="briareus:platform",
                leeway=0,
                options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp"]},
            )
            if not isinstance(result, dict):
                raise OwnerAuthorityUnavailable("Team proof is not a signed JWT object")
            return claims_type.model_validate_json(
                json.dumps(result, separators=(",", ":"), allow_nan=False)
            )
        except (jwt.PyJWTError, ValueError, TypeError):
            raise OwnerAuthorityUnavailable("signed Team owner claim rejected") from None

    @staticmethod
    def _fresh(iat: int, nbf: int, exp: int) -> None:
        now = datetime.now(UTC)
        issued = datetime.fromtimestamp(iat, UTC)
        not_before = datetime.fromtimestamp(nbf, UTC)
        expires = datetime.fromtimestamp(exp, UTC)
        if (
            issued > now
            or not_before > now
            or expires <= now
            or now - issued > timedelta(seconds=15)
            or expires - issued > timedelta(seconds=30)
        ):
            raise OwnerAuthorityUnavailable("Team proof is stale or revoked")

    def verify(
        self, command: TeamOwnerCommandDTO, proofs: SignedTeamProofs
    ) -> VerifiedTeamOperation:
        seen: dict[str, TeamOwnerProofClaims] = {}
        for owner in ("identity", "platform", "access"):
            pin = self._pins[owner]
            source = getattr(proofs, owner)
            claim = self._decode(source, pin, TeamOwnerProofClaims)
            expected = {
                "identity": command.expected_identity_revision,
                "platform": command.expected_team_revision,
                "access": command.expected_access_revision,
            }[owner]
            if (
                claim.owner != owner
                or claim.owner_database != OWNER_DB_NAMES[owner]
                or claim.aud != self._audience
                or claim.sub != str(command.caller_user_id)
                or claim.team_id != command.team_id
                or claim.caller_user_id != command.caller_user_id
                or claim.operation_uuid != command.operation_uuid
                or claim.operation != command.operation
                or claim.idempotency_key != command.idempotency_key
                or claim.payload_sha256 != command.payload_sha256
                or claim.owner_revision != expected
                or not claim.active
                or claim.authority_epoch.version != 4
                or (owner != "identity" and command.operation not in claim.capabilities)
            ):
                raise OwnerAuthorityUnavailable("signed Team identity/scope/rights mismatch")
            self._fresh(claim.iat, claim.nbf, claim.exp)
            seen[owner] = claim
        role = seen["identity"].role
        if role not in {"user", "superuser"}:
            raise OwnerAuthorityUnavailable("current Identity role was not signed")
        return VerifiedTeamOperation(
            command,
            role,
            seen["identity"].authority_epoch,
            seen["platform"].authority_epoch,
            seen["access"].authority_epoch,
            datetime.now(UTC),
        )

    def verify_target(self, command: TeamOwnerCommandDTO, target_id: UUID, token: SecretStr) -> int:
        claim = self._decode(token, self._pins["identity"], IdentityTargetProofClaims)
        if (
            claim.sub != str(target_id)
            or claim.target_user_id != target_id
            or claim.team_id != command.team_id
            or claim.operation_uuid != command.operation_uuid
            or not claim.enabled
        ):
            raise OwnerAuthorityUnavailable("Team target User no longer enabled")
        self._fresh(claim.iat, claim.nbf, claim.exp)
        return claim.credential_version

    @staticmethod
    def check_payload(
        command: TeamOwnerCommandDTO, payload: TeamMemberPayload | TeamOwnerTransferPayload
    ) -> None:
        digest = hashlib.sha256(
            json.dumps(
                asdict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        if digest != command.payload_sha256:
            raise OwnerAuthorityUnavailable("Team effect differs from signed original payload")


async def require_current_team(
    authority: TeamOwnerProofAuthority,
    source: CurrentTeamOwnerPort,
    command: TeamOwnerCommandDTO,
) -> VerifiedTeamOperation:
    try:
        async with asyncio.timeout(3):
            proofs = await source.fetch_current(command)
        return authority.verify(command, proofs)
    except Exception:
        raise OwnerAuthorityUnavailable("current signed Team/Identity/Access unavailable") from None
