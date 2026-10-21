"""Short-lived Resources placement projection for the global Gateway."""
from urllib.parse import urlsplit

from pydantic import Field, UUID4, field_validator

from .models import Contract


class NodeRoute(Contract):
    node_uuid: UUID4
    placement_uuid: UUID4
    project_uuid: UUID4
    module: str = Field(pattern=r"^(files|terminal|web|svc|infrastructure|reverse|serena)$")
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    port: int = Field(strict=True, ge=1024, le=65535)
    origin: str = Field(max_length=512)
    expires_at: int = Field(strict=True, ge=1)

    @field_validator("origin")
    @classmethod
    def canonical_origin(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or parsed.port not in {None, 443}
            or value != "https://" + parsed.hostname):
            raise ValueError("Canonical TLS node origin required")
        return value
