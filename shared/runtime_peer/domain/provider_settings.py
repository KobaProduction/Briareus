"""Credential-free provider metadata; omitted fields remain distinct from explicit null."""

from dataclasses import dataclass
from enum import Enum


class OmittedProviderField(Enum):
    OMITTED = "omitted"


OMITTED = OmittedProviderField.OMITTED


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    base_url: str | OmittedProviderField = OMITTED
    display_name: str | OmittedProviderField = OMITTED
    installation_id: int | str | float | bool | OmittedProviderField | None = OMITTED
    organization: str | OmittedProviderField = OMITTED
    namespace: str | OmittedProviderField = OMITTED
    tenant: str | OmittedProviderField = OMITTED
