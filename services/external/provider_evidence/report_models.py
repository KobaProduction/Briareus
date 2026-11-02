"""Explicit views for the existing read-only CLI evidence report."""

from collections.abc import Callable
from functools import partial
from operator import is_
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import MISSING

from .domain import DiscoveryEvidence


class EvidenceView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublicStatusView(EvidenceView):
    discovery_status: int
    public_pass: bool


class PublicFailureView(EvidenceView):
    error_type: str
    public_pass: Literal[False] = False


class PublicEvidenceView(PublicStatusView):
    discovery_contract: DiscoveryEvidence
    jwks_status: int
    jwks_no_private_fields: bool
    jwks_public_keys: int | MISSING = MISSING
    public_jwks_sha256: str | MISSING | None = MISSING
    public_admin_probe_statuses: dict[str, int]
    admin_route_privacy_accepted: bool
    self_user_by_id_without_session_status: int
    self_user_route_unauthenticated_gate: bool
    representative_registration_get_statuses: dict[str, int]
    public_oidc_pass: bool
    public_self_profile_required: Literal[False] = False
    real_self_profile_login: Literal["NOT_PROVEN_NO_USER_SESSION"] = "NOT_PROVEN_NO_USER_SESSION"
    signup_disabled_everywhere: Literal["NOT_PROVEN_BY_PUBLIC_GET"] = "NOT_PROVEN_BY_PUBLIC_GET"
    valid_user_code_flow: Literal["NOT_PROVEN_NO_USER_CREDENTIALS"] = (
        "NOT_PROVEN_NO_USER_CREDENTIALS"
    )
    # Fixed diagnostic status, never credential material.
    resource_token_audience: Literal["NOT_PROVEN_NO_SIGNED_MCP_TOKEN"] = (
        "NOT_PROVEN_NO_SIGNED_MCP_TOKEN"  # noqa: S105
    )
    registered_client_redirect: Literal["NOT_PROVEN_NO_PRIVATE_CLIENT_PROOF"] = (
        "NOT_PROVEN_NO_PRIVATE_CLIENT_PROOF"
    )
    native_control_panel_login: Literal["NOT_PROVEN_NO_NATIVE_BFF_CHALLENGE_FLOW"] = (
        "NOT_PROVEN_NO_NATIVE_BFF_CHALLENGE_FLOW"
    )


_no_public_evidence: Callable[
    [PublicEvidenceView | PublicStatusView | PublicFailureView | None], bool
] = partial(is_, None)


class ProviderReportView(EvidenceView):
    # Named checks and per-Compose flag indexes contain only boolean evidence.
    source: dict[str, bool | dict[str, bool]]
    public: PublicEvidenceView | PublicStatusView | PublicFailureView | None = Field(
        default=None,
        exclude_if=_no_public_evidence,
    )
