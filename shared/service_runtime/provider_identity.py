"""Stable provider identity documents, with no credentials or execution dependencies."""

from collections.abc import Callable
from functools import partial
from operator import is_

from pydantic import BaseModel, ConfigDict, Field

unreported: Callable[[object], bool] = partial(is_, None)


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True, serialize_by_alias=True, hide_input_in_errors=True
    )


class SigNozResource(ProviderMetadata):
    kind: str
    type: str


class SigNozObjectGroup(ProviderMetadata):
    resource: SigNozResource
    selectors: list[str]


class SigNozTransaction(ProviderMetadata):
    relation: str
    object_group: SigNozObjectGroup = Field(alias="objectGroup")


class SigNozRole(ProviderMetadata):
    id: str
    name: str
    description: str
    type: str
    org_id: str = Field(alias="orgId")
    transaction_groups: list[SigNozTransaction] = Field(alias="transactionGroups")
    created_at: str | None = Field(default=None, alias="createdAt", exclude_if=unreported)
    updated_at: str | None = Field(default=None, alias="updatedAt", exclude_if=unreported)


class SigNozServiceAccountRole(ProviderMetadata):
    id: str
    role_id: str = Field(alias="roleId")
    service_account_id: str = Field(alias="serviceAccountId")
    role: SigNozRole
    created_at: str | None = Field(default=None, alias="createdAt", exclude_if=unreported)
    updated_at: str | None = Field(default=None, alias="updatedAt", exclude_if=unreported)


class SigNozServiceAccount(ProviderMetadata):
    id: str
    name: str
    email: str
    status: str
    org_id: str = Field(alias="orgId")
    service_account_roles: list[SigNozServiceAccountRole] | None = Field(
        alias="serviceAccountRoles"
    )
    created_at: str | None = Field(default=None, alias="createdAt", exclude_if=unreported)
    updated_at: str | None = Field(default=None, alias="updatedAt", exclude_if=unreported)


class SigNozReply[T](ProviderMetadata):
    status: str
    data: T


class CoolifyTeamMetadata(ProviderMetadata):
    id: int | None = None
    name: str | None = None
    description: str | None = None
    personal_team: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None
