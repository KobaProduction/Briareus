"""Existing browser request contracts for provider reset and recovery."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SetupCode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: str = Field(pattern=r"^[A-Za-z0-9]{24}$")
    code: SecretStr


class SetupPassword(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    password: SecretStr


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    pow: SecretStr
