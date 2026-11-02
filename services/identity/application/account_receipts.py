"""Credential-free Identity command receipts, also used to validate sealed replay."""

from typing import Literal

from pydantic import UUID4, BaseModel, ConfigDict, Field, StrictBool, StrictInt


class AccountRevisionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    user_id: UUID4
    credential_version: StrictInt = Field(ge=1)


class AccountChangedReceipt(AccountRevisionReceipt):
    enabled: StrictBool
    role: str = Field(pattern=r"^(user|superuser)$")
    deleted: StrictBool


class UserDeletedReceipt(AccountRevisionReceipt):
    deleted: Literal[True]
    reconciliation_required: Literal[True]
