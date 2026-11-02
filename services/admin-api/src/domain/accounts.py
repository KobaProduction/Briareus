"""Account identity and provider invariants, independent of API serialization."""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
from uuid import uuid4

from .validation import require_boolean, require_datetime, require_text


class AccountConflictError(RuntimeError):
    """Raised when an account update targets a stale persisted revision."""


class Provider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"
    SIGNOZ = "signoz"
    COOLIFY = "coolify"


class AuthType(StrEnum):
    """Member names are stable wire identifiers; StrEnum emits their lowercase form."""

    GITHUB_APP = auto()
    GITHUB_TOKEN = auto()
    PRIVATE_TOKEN = auto()
    BEARER = auto()
    JOB_TOKEN = auto()
    SIGNOZ_API_KEY = auto()
    COOLIFY_API_TOKEN = auto()


def require_account_kinds(provider: object, auth_type: object) -> None:
    if not isinstance(provider, Provider) or not isinstance(auth_type, AuthType):
        raise ValueError("Typed account provider and authentication kind required")


@dataclass(frozen=True, slots=True, kw_only=True)
class Account:
    id: str = field(default_factory=lambda: str(uuid4()))
    alias: str
    provider: Provider
    auth_type: AuthType
    base_url: str = ""
    external_id: str = ""
    verify_tls: bool = True
    ca_cert_pem: str = ""
    enabled: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_fields()
        if self.provider is Provider.GITHUB:
            self._normalize_github()
        else:
            self._normalize_web_provider()

    def _validate_identity(self) -> None:
        require_account_kinds(self.provider, self.auth_type)
        require_text(self.id, name="id")
        if re.fullmatch(r"[0-9a-f-]{36}", self.id) is None:
            raise ValueError("Account identifier must have 36 lowercase hex/hyphen characters")
        require_text(self.alias, name="alias")
        alias = self.alias.strip().casefold()
        require_text(alias, name="alias", minimum=1, maximum=128)
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", alias) is None:
            raise ValueError("Account alias must use letters, digits, dot, underscore or hyphen")
        object.__setattr__(self, "alias", alias)

    def _validate_fields(self) -> None:
        require_text(self.base_url, name="base_url", maximum=2048)
        require_text(self.external_id, name="external_id", maximum=512)
        require_text(self.ca_cert_pem, name="ca_cert_pem", maximum=65536)
        object.__setattr__(self, "base_url", self.base_url.strip())
        object.__setattr__(self, "external_id", self.external_id.strip())
        object.__setattr__(self, "ca_cert_pem", self.ca_cert_pem.strip())
        require_boolean(self.verify_tls, name="verify_tls")
        require_boolean(self.enabled, name="enabled")
        require_datetime(self.created_at, name="created_at")
        require_datetime(self.updated_at, name="updated_at")

    def _normalize_github(self) -> None:
        if self.auth_type not in {AuthType.GITHUB_APP, AuthType.GITHUB_TOKEN}:
            raise ValueError("GitHub auth_type must be github_app or github_token")
        if self.auth_type is AuthType.GITHUB_APP and not self.external_id:
            raise ValueError("GitHub App accounts require external_id=APP_ID")
        if self.auth_type is AuthType.GITHUB_TOKEN:
            object.__setattr__(self, "external_id", "")
        object.__setattr__(self, "base_url", "https://api.github.com")
        object.__setattr__(self, "verify_tls", True)
        object.__setattr__(self, "ca_cert_pem", "")

    def _web_default_url(self) -> str:
        if self.provider is Provider.GITLAB:
            if self.auth_type not in {AuthType.PRIVATE_TOKEN, AuthType.BEARER, AuthType.JOB_TOKEN}:
                raise ValueError("GitLab auth_type must be token based")
            return "https://gitlab.com"
        if self.provider is Provider.SIGNOZ:
            if self.auth_type is not AuthType.SIGNOZ_API_KEY:
                raise ValueError("SigNoz auth_type must be signoz_api_key")
            return ""
        if self.provider is Provider.COOLIFY:
            if self.auth_type is not AuthType.COOLIFY_API_TOKEN:
                raise ValueError("Coolify auth_type must be coolify_api_token")
            return ""
        raise ValueError(f"unsupported provider: {self.provider.value}")

    def _normalize_web_provider(self) -> None:
        default_url = self._web_default_url()
        base_url = (self.base_url or default_url).rstrip("/")
        parsed = urllib.parse.urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                f"{self.provider.value} base_url must be an http(s) URL without credentials/query"
            )
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "external_id", "")
