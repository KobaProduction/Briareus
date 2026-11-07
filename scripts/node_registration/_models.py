from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from typing import Literal, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ErrorCode(StrEnum):
    REJECTED = "provisioning_rejected"
    UNAVAILABLE = "provisioning_unavailable"
    UNCERTAIN = "registration_unconfirmed"
    INVALID_RESPONSE = "invalid_provider_response"
    CONFIGURATION = "invalid_registration_configuration"
    DEPLOYMENT = "deployment_failed_role_preserved"


class NodeRegistrationError(Exception):
    def __init__(self, code: ErrorCode, node: str = "", status: int | None = None) -> None:
        super().__init__(code.value)
        self.code = code
        self.node = node
        self.status = status


def origin(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    local = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ValueError("An HTTPS origin is required, except localhost test origins")
    if (
        not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or value != value.strip()
    ):
        raise ValueError("An origin cannot contain credentials, a path, a query or a fragment")
    _port = parsed.port
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


class NodeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    origin: str = Field(max_length=2048)

    @field_validator("origin")
    @classmethod
    def _origin(cls, value: str) -> str:
        result = origin(value)
        host = urlsplit(result).hostname or ""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in host.split(".")
            ):
                raise ValueError("A node origin must have DNS labels") from None
            return result
        raise ValueError("A node requires a DNS name rather than an IP address")

    @property
    def node_id(self) -> str:
        return (urlsplit(self.origin).hostname or "").split(".")[0]


class RegistryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    issuer: str = Field(max_length=2048)
    project_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,200}$")
    token: SecretStr = Field(repr=False)

    @field_validator("issuer")
    @classmethod
    def _issuer(cls, value: str) -> str:
        return origin(value)

    @field_validator("token")
    @classmethod
    def _token(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if not text or text != text.strip() or any(char.isspace() for char in text):
            raise ValueError("A provisioning credential is required")
        return value


class RoleRegistry(Protocol):
    def ensure(self, node: NodeSpec) -> bool:
        """Return whether a missing role was created; preserve an existing role."""
        ...


class NodeRuntime(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, populate_by_name=True)
    required_role: str = Field(serialization_alias="OIDC_REQUIRED_ROLE")


class NodeResult(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)
    status: Literal["created", "existing"]
    node: str
    origin: str
    runtime: NodeRuntime
