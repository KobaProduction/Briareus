"""Pinned Rauthy v0.37.1 OTP request bodies at the provider boundary."""

from pydantic import BaseModel, ConfigDict, Field


class NativeOtpLoginPurpose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    login_code: str = Field(alias="Login", repr=False)


class NativeOtpStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    otp_id: str = Field(repr=False)
    purpose: NativeOtpLoginPurpose = Field(repr=False)


class NativeOtpFinishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    code: str = Field(repr=False)
    otp_code: str = Field(repr=False)
