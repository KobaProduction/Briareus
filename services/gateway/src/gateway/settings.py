from __future__ import annotations

from urllib.parse import urlsplit

from briareus_environment_models import ProcessSettings
from briareus_http_surface import HttpSurfaceSettings
from pydantic import AliasChoices, Field, field_validator


class GatewaySettings(ProcessSettings):
    build_sha: str = Field(
        "unknown",
        validation_alias=AliasChoices("BUILD_SHA", "SOURCE_COMMIT"),
    )
    build_time: str = Field("unknown", validation_alias="BUILD_TIME")
    @field_validator("build_sha", "build_time", mode="before")
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @staticmethod
    def http_for_origin(public_origin: str) -> HttpSurfaceSettings:
        """Use the single trusted public URL for FastMCP's Host and Origin checks."""
        parsed = urlsplit(public_origin)
        host = parsed.hostname
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("Gateway public origin has an invalid port") from error
        local = host in {"localhost", "127.0.0.1", "::1"} or (
            host is not None and host.endswith(".localhost")
        )
        if (
            (parsed.scheme != "https" and not (parsed.scheme == "http" and local))
            or not host
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or public_origin != public_origin.strip()
            or not public_origin.isascii()
            or any(character.isspace() or ord(character) < 32 for character in public_origin)
            or parsed.netloc.endswith(":")
            or any(character in parsed.netloc for character in ("*", ",", "%", " "))
            or (port is not None and port == 0)
        ):
            raise ValueError("Gateway requires one validated HTTPS public origin")
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return HttpSurfaceSettings(
            allowed_hosts=(parsed.netloc,),
            allowed_origins=(origin,),
        )
