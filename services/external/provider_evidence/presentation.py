"""The existing flat CLI JSON report, serialized only at the output boundary."""

from __future__ import annotations

import json

from pydantic_core import MISSING

from .domain import PublicFailure, PublicReport, SourceReport
from .report_models import (
    ProviderReportView,
    PublicEvidenceView,
    PublicFailureView,
    PublicStatusView,
)


def render_report(source: SourceReport, public: PublicReport | PublicFailure | None) -> str:
    source_fields: dict[str, bool | dict[str, bool]] = {
        check.name: check.passed for check in source.checks
    }
    for compose in source.compose:
        source_fields.update({check.name: check.passed for check in compose.checks})
        source_fields[compose.filename + ".security_fields"] = {
            flag.name: flag.disabled for flag in compose.security_fields
        }
    source_fields["source_pass"] = source.source_pass
    public_view: PublicEvidenceView | PublicStatusView | PublicFailureView | None = None
    if isinstance(public, PublicFailure):
        public_view = PublicFailureView(error_type=public.error_type)
    elif public is not None:
        public_view = _public_view(public)
    report = ProviderReportView(source=source_fields, public=public_view)
    return json.dumps(report.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def _public_view(report: PublicReport) -> PublicEvidenceView | PublicStatusView:
    discovery, keys = report.discovery, report.keys
    if discovery is None:
        return PublicStatusView(
            discovery_status=report.discovery_status, public_pass=report.public_pass
        )
    if keys is None:
        raise ValueError("Complete public key evidence required")
    return PublicEvidenceView(
        discovery_status=report.discovery_status,
        public_pass=report.public_pass,
        discovery_contract=discovery,
        jwks_status=keys.status,
        jwks_no_private_fields=keys.no_private_fields,
        jwks_public_keys=keys.count if keys.count is not None else MISSING,
        public_jwks_sha256=keys.sha256 if keys.count is not None else MISSING,
        public_admin_probe_statuses={
            route.name: route.status
            for route in report.routes
            if route.name in {"admin", "admin_attributes", "admin_clients"}
        },
        admin_route_privacy_accepted=report.admin_route_privacy_accepted,
        self_user_by_id_without_session_status=report.self_user_status,
        self_user_route_unauthenticated_gate=report.self_user_status in {401, 403, 404},
        representative_registration_get_statuses={
            route.path: route.status
            for route in report.routes
            if route.name in {"registration_users", "registration_root"}
        },
        public_oidc_pass=report.public_oidc_pass,
    )
