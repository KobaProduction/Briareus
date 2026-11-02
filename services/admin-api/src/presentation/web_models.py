"""Existing HTTP-only administration payload contracts."""

from __future__ import annotations

from datetime import datetime

from domain.accounts import AuthType, Provider
from pydantic import BaseModel, ConfigDict, Field

from common.access_contracts import (
    AccessLevel,
    AccountScope,
    EnforcementMode,
)


class AccessResolvePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approve: bool
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = None
    expires_at: int | None = Field(default=None, ge=0)


class AccessSessionUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_level: AccessLevel | None = None
    account_scope: AccountScope | None = None
    account_ids: list[str] | None = None
    expires_at: int | None = Field(default=None, ge=0)
    label: str | None = Field(default=None, max_length=256)


class AccessControlItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    surface_id: int
    mode: EnforcementMode


class AccessControlBatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AccessControlItem] = Field(min_length=1, max_length=100)


class AccountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str
    provider: Provider
    auth_type: AuthType
    base_url: str = ""
    external_id: str = ""
    verify_tls: bool = True
    ca_cert_pem: str = ""
    enabled: bool = True
    credential: str = ""


class AccountUpdatePayload(AccountPayload):
    expected_updated_at: datetime | None = None


class AccountCandidatePayload(AccountPayload):
    alias: str = Field(min_length=1, max_length=128)
    base_url: str = Field("", max_length=2048)
    external_id: str = Field("", max_length=512)
    ca_cert_pem: str = Field("", max_length=65_536)
    credential: str = Field("", max_length=131_072)
    account_id: str = Field("", max_length=36)
    draft_revision: str = Field(min_length=1, max_length=128)


class ProjectCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    parent_dir: str = ""


class WorkerControlPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class WorkerRecoverPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeout_seconds: float = Field(4.0, ge=1.0, le=30.0)
