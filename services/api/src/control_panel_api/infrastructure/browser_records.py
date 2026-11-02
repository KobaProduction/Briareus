"""Named private Valkey records decoded only after duplicate-field validation."""

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from control_panel_api.domain.native_login import PrivateNativeOtpPending, PrivateNativePending
from control_panel_api.domain.oidc_identity import PrivateOidcResourceCredential
from control_panel_api.infrastructure.json_fields import validate_unique_fields


class StoredTransaction(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    issuer: str
    client_id: str
    nonce: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)
    verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)
    expires_at: datetime
    resource_audience: str | None


class StoredNativeInit(StoredTransaction):
    stage: Literal["init"]
    state: str
    csrf: str = Field(pattern=r"^[A-Za-z0-9]{32}$", repr=False)
    provider_cookie: str = Field(repr=False)
    deadline_ms: int


class StoredNativeClaim(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    stage: Literal["claimed"]
    claim: str = Field(repr=False)


class StoredOtpMethod(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    kind: Literal["email"]
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$", repr=False)


class StoredNativeOtp(BaseModel):
    model_config = ConfigDict(strict=True, hide_input_in_errors=True)
    stage: Literal["otp_ready", "otp_started"]
    state: str
    issuer: str
    client_id: str
    deadline_ms: int
    claim: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)
    nonce: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)
    verifier: str = Field(pattern=r"^[A-Za-z0-9_-]{32,128}$", repr=False)
    csrf: str = Field(pattern=r"^[A-Za-z0-9]{32}$", repr=False)
    provider_cookie: str = Field(max_length=12288, repr=False)
    resource_audience: str | None = None
    methods: tuple[StoredOtpMethod, ...] | None = None
    selected_otp_id: str | None = Field(default=None, repr=False)
    otp_login_code: str | None = Field(default=None, repr=False)
    otp_code: str | None = Field(default=None, repr=False)
    otp_expires_ms: int | None = None

    def valid_stage(self) -> bool:
        if self.stage == "otp_ready":
            return (
                self.methods is not None
                and 1 <= len(self.methods) <= 10
                and self.selected_otp_id in {method.id for method in self.methods}
                and self.otp_login_code is not None
                and re.fullmatch(r"[A-Za-z0-9_-]{16,256}", self.otp_login_code, re.ASCII)
                is not None
                and "otp_code" not in self.model_fields_set
            )
        return (
            self.otp_code is not None
            and re.fullmatch(r"[A-Za-z0-9]{48}", self.otp_code, re.ASCII) is not None
            and self.otp_expires_ms is not None
            and self.otp_expires_ms > int(datetime.now(UTC).timestamp() * 1000)
            and not self.model_fields_set.intersection(
                {"methods", "selected_otp_id", "otp_login_code"}
            )
        )

    def pending(
        self, *, state: str, issuer: str, client_id: str, attempt_id: SecretStr
    ) -> PrivateNativeOtpPending | None:
        deadline = datetime.fromtimestamp(self.deadline_ms / 1000, UTC)
        if (
            (self.state, self.issuer, self.client_id) != (state, issuer, client_id)
            or deadline <= datetime.now(UTC)
            or not self.provider_cookie.startswith("__Host-RauthySession=")
            or not self.valid_stage()
        ):
            return None
        original = PrivateNativePending(
            state=state,
            issuer=issuer,
            client_id=client_id,
            nonce=self.nonce,
            verifier=SecretStr(self.verifier),
            csrf=SecretStr(self.csrf),
            provider_cookie=SecretStr(self.provider_cookie),
            expires_at=deadline,
            claim_id=SecretStr(self.claim),
            resource_audience=self.resource_audience,
        )
        return PrivateNativeOtpPending(
            original=original,
            attempt_id=attempt_id,
            selected_otp_id=SecretStr(self.selected_otp_id)
            if self.selected_otp_id is not None
            else None,
            login_code=SecretStr(self.otp_login_code) if self.otp_login_code is not None else None,
            finish_code=SecretStr(self.otp_code) if self.otp_code is not None else None,
            provider_cookie=SecretStr(self.provider_cookie),
        )


class StoredResource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    bearer: str = Field(min_length=80, max_length=8192, repr=False)
    expires_at: datetime


class StoredBrowserResource(StoredResource):
    audience: str


class StoredBrowserRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    token: str = Field(repr=False)
    not_before: datetime
    expires_at: datetime | None = None


class StoredBrowserSession(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    issuer: str
    subject: str
    client_id: str
    expires_at: datetime
    resource: StoredBrowserResource | None = None
    session_expires_at: datetime | None = None
    refresh: StoredBrowserRefresh | None = None
    refresh_attempt: str | None = Field(default=None, repr=False)
    mcp_resources: dict[str, StoredResource] = Field(default_factory=dict)


def browser_record[Record: BaseModel](raw: str, model: type[Record]) -> Record:
    validate_unique_fields(raw)
    return model.model_validate_json(raw)


def private_secret(value: object) -> bool:
    return isinstance(value, SecretStr)


def valid_resource_type(value: object) -> bool:
    return isinstance(value, PrivateOidcResourceCredential)
