"""The existing public provider options wire shape; credentials are never metadata."""

from typing import Self

from pydantic import BaseModel, ConfigDict, StrictBool, StrictFloat, StrictInt, StrictStr
from pydantic_core import MISSING

from .domain.provider_settings import OMITTED, ProviderSettings


class ProviderSettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str | MISSING = MISSING
    display_name: str | MISSING = MISSING
    # Retain the original accepted scalar until the owner validates/coerces it.
    # Idempotency fingerprints must distinguish e.g. "42", 42 and 42.0.
    installation_id: StrictInt | StrictStr | StrictFloat | StrictBool | MISSING | None = MISSING
    organization: str | MISSING = MISSING
    namespace: str | MISSING = MISSING
    tenant: str | MISSING = MISSING

    def record(self) -> ProviderSettings:
        return ProviderSettings(
            OMITTED if self.base_url is MISSING else self.base_url,
            OMITTED if self.display_name is MISSING else self.display_name,
            OMITTED if self.installation_id is MISSING else self.installation_id,
            OMITTED if self.organization is MISSING else self.organization,
            OMITTED if self.namespace is MISSING else self.namespace,
            OMITTED if self.tenant is MISSING else self.tenant,
        )

    @classmethod
    def from_record(cls, value: ProviderSettings) -> Self:
        return cls(
            base_url=MISSING if value.base_url is OMITTED else value.base_url,
            display_name=MISSING if value.display_name is OMITTED else value.display_name,
            installation_id=MISSING if value.installation_id is OMITTED else value.installation_id,
            organization=MISSING if value.organization is OMITTED else value.organization,
            namespace=MISSING if value.namespace is OMITTED else value.namespace,
            tenant=MISSING if value.tenant is OMITTED else value.tenant,
        )
