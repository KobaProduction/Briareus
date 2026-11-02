#!/usr/bin/env python3
"""Read-only Rauthy release evidence, never a client/user provisioning tool.

Fixed Development origin only; no credentials, redirects, privileged REST,
database query or login. Provider cookies/tokens never appear in the report.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path
from urllib.error import URLError

from provider_evidence.application import InspectPublicProvider, InspectSource, ProbeRoute
from provider_evidence.domain import ProviderEndpoints, PublicFailure, PublicReport, SourceReport
from provider_evidence.infrastructure import (
    FixedOriginProbe,
    LocalProviderSource,
    ProviderJsonCodec,
)
from provider_evidence.presentation import render_report

PUBLIC_ORIGIN = "https://briareus.koba-nexus.ru"
ISSUER = PUBLIC_ORIGIN + "/auth/v1/"
DISCOVERY = ISSUER + ".well-known/openid-configuration"
AUTHORIZATION = ISSUER + "oidc/authorize"
TOKEN = ISSUER + "oidc/token"
JWKS = ISSUER + "oidc/certs"
COMPOSE_DIR = Path(__file__).resolve().parent


def _source_checks() -> SourceReport:
    return InspectSource(LocalProviderSource(COMPOSE_DIR)).execute()


def _public_checks() -> PublicReport:
    routes = (
        ProbeRoute("admin", "/auth/v1/users"),
        ProbeRoute("self_user_by_id", "/auth/v1/users/" + secrets.token_hex(12)),
        ProbeRoute("admin_attributes", "/auth/v1/users/attr"),
        ProbeRoute("admin_clients", "/auth/v1/clients"),
        ProbeRoute("registration_users", "/auth/v1/users/register"),
        ProbeRoute("registration_root", "/auth/v1/register"),
    )
    return InspectPublicProvider(
        FixedOriginProbe(PUBLIC_ORIGIN),
        ProviderJsonCodec(),
        ProviderEndpoints(ISSUER, AUTHORIZATION, TOKEN, JWKS),
        routes,
    ).execute()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--public",
        action="store_true",
        help="also check fixed public HTTPS OIDC endpoints without credentials",
    )
    args = parser.parse_args()
    source = _source_checks()
    public: PublicReport | PublicFailure | None = None
    if args.public:
        try:
            public = _public_checks()
        except (URLError, TimeoutError, ValueError, KeyError, TypeError) as error:
            public = PublicFailure(type(error).__name__)
    print(render_report(source, public))
    public_pass = public is None or (isinstance(public, PublicReport) and public.public_pass)
    return 0 if source.source_pass and public_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
