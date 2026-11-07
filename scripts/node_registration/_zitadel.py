from __future__ import annotations

from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ._models import ErrorCode, NodeRegistrationError, NodeSpec, RegistryConfig


class _RoleExists(Exception):
    """A concurrent installer already created the same role."""


class _WireModel(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)


class _CreateRole(_WireModel):
    project_id: str = Field(serialization_alias="projectId")
    role_key: str = Field(serialization_alias="roleKey")
    display_name: str = Field(serialization_alias="displayName")
    group: str = "Nodes"


class _Created(_WireModel):
    creation_date: datetime = Field(validation_alias="creationDate")


class _KeyFilter(_WireModel):
    key: str
    method: str = "TEXT_FILTER_METHOD_EQUALS"


class _RoleFilter(_WireModel):
    key: _KeyFilter = Field(serialization_alias="roleKeyFilter")


class _FindRole(_WireModel):
    project_id: str = Field(serialization_alias="projectId")
    filters: list[_RoleFilter]


class _Role(_WireModel):
    project_id: str = Field(validation_alias="projectId")
    key: str


class _Roles(_WireModel):
    project_roles: list[_Role] = Field(default_factory=list, validation_alias="projectRoles")


class ZitadelRoleRegistry:
    """Role administration stays in the deployment runner, outside node runtimes."""

    def __init__(self, config: RegistryConfig, client: httpx.Client) -> None:
        self.config = config
        self.client = client

    def ensure(self, node: NodeSpec) -> bool:
        if self._exists(node):
            return False
        payload = _CreateRole(
            project_id=self.config.project_id,
            role_key=node.node_id,
            display_name=node.node_id.capitalize(),
        )
        try:
            self._request("AddProjectRole", payload, _Created, node, creating=True)
        except _RoleExists:
            return False
        return True

    def _exists(self, node: NodeSpec) -> bool:
        payload = _FindRole(
            project_id=self.config.project_id,
            filters=[_RoleFilter(key=_KeyFilter(key=node.node_id))],
        )
        result = self._request("ListProjectRoles", payload, _Roles, node, creating=False)
        return any(
            role.key == node.node_id and role.project_id == self.config.project_id
            for role in result.project_roles
        )

    def _request[T: BaseModel](
        self,
        operation: str,
        payload: BaseModel,
        model: type[T],
        node: NodeSpec,
        *,
        creating: bool,
    ) -> T:
        url = self.config.issuer + "/zitadel.project.v2.ProjectService/" + operation
        headers = {
            "Authorization": "Bearer " + self.config.token.get_secret_value(),
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        }
        try:
            with self.client.stream(
                "POST",
                url,
                headers=headers,
                content=payload.model_dump_json(by_alias=True),
                follow_redirects=False,
            ) as response:
                self._check_status(response.status_code, node, creating=creating)
                return self._decode(response, model)
        except (httpx.HTTPError, ValidationError, ValueError):
            code = ErrorCode.UNCERTAIN if creating else ErrorCode.INVALID_RESPONSE
            raise NodeRegistrationError(code, node.node_id) from None

    @staticmethod
    def _check_status(status: int, node: NodeSpec, *, creating: bool) -> None:
        if status == 409 and creating:
            raise _RoleExists
        if status != 200:
            raise NodeRegistrationError(ErrorCode.REJECTED, node.node_id, status)

    @staticmethod
    def _decode[T: BaseModel](response: httpx.Response, model: type[T]) -> T:
        body = bytearray()
        for chunk in response.iter_bytes(chunk_size=8192):
            body.extend(chunk)
            if len(body) > 65536:
                raise ValueError("Provider response exceeds the deployment protocol limit")
        return model.model_validate_json(bytes(body))
