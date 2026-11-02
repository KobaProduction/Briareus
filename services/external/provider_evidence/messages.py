"""Concrete source inventory and public discovery projections at the read-only boundary."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, StrictStr, field_validator

from .domain import DatabaseInventory, DiscoveryEvidence, ProviderEndpoints


def _optional_text(value: object) -> str | None:
    # Provider metadata with the wrong type is negative evidence, never an endpoint.
    return value if isinstance(value, str) else None


type EvidenceText = Annotated[str | None, BeforeValidator(_optional_text)]


class EvidenceMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)


class DatabaseOwnerMessage(EvidenceMessage):
    database: StrictStr


class DatabaseInventoryMessage(EvidenceMessage):
    initial: tuple[DatabaseOwnerMessage, ...]
    protected_provider_databases: tuple[StrictStr, ...]
    excluded_legacy_databases_do_not_touch_automatically: tuple[StrictStr, ...]

    def inventory(self) -> DatabaseInventory:
        return DatabaseInventory(
            frozenset(row.database for row in self.initial),
            frozenset(self.protected_provider_databases),
            frozenset(self.excluded_legacy_databases_do_not_touch_automatically),
        )


class DiscoveryMessage(EvidenceMessage):
    issuer: EvidenceText = None
    authorization_endpoint: EvidenceText = None
    token_endpoint: EvidenceText = None
    jwks_uri: EvidenceText = None
    response_types_supported: tuple[str, ...] = ()
    code_challenge_methods_supported: tuple[str, ...] = ()

    @field_validator("response_types_supported", "code_challenge_methods_supported", mode="before")
    @classmethod
    def capabilities(cls, value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(item for item in value if isinstance(item, str))

    def evidence(self, expected: ProviderEndpoints) -> DiscoveryEvidence:
        return DiscoveryEvidence(
            self.issuer == expected.issuer,
            self.authorization_endpoint == expected.authorization,
            self.token_endpoint == expected.token,
            self.jwks_uri == expected.jwks,
            "code" in self.response_types_supported,
            "S256" in self.code_challenge_methods_supported,
        )


class PublicKeyMetadata(EvidenceMessage):
    kid: EvidenceText = None
