"""BFF-to-Authorization wire data for human browser effect evidence."""

from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, SecretStr


class HumanEffectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    module: Literal["web", "files", "terminal", "reverse"] = "web"
    project_uuid: UUID4
    request_uuid: UUID4
    bearer: SecretStr = Field(min_length=1, max_length=8192)
    body: str = Field(min_length=1, max_length=43692, repr=False)


class HumanPermitReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    permit: str = Field(min_length=1, max_length=8192, repr=False)
