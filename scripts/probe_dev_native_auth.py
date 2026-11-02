#!/usr/bin/env python3
"""Bounded public Development native-login ingress check; no credentials.

Source and deployment readiness are different. This probe never follows
redirects, submits a password, reads an operator secret, or claims a Cedar
Permit. One pinned public Briareus Development origin, explicit GETs only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from http.client import HTTPException, HTTPMessage
from typing import IO, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ORIGIN = "https://briareus.koba-nexus.ru"
ISSUER = ORIGIN + "/auth/v1/"
MAX_BYTES = 8192
TIMEOUT = 7
PATHS = (
    "/panel/",
    "/api/v1/auth/capabilities",
    "/api/v1/auth/session",
    "/api/auth/native/capabilities",
    "/auth/v1/.well-known/openid-configuration",
    "/auth/v1/users",
    "/auth/v1/users/attr",
    "/auth/v1/clients",
)


class PublicProbe(NamedTuple):
    status: int
    content_type: str
    body: bytes
    redirected: bool
    cache_control: str
    pragma: str
    sets_cookie: bool


class ProbeReading(NamedTuple):
    path: str
    probe: PublicProbe


class ProbeStatus(NamedTuple):
    path: str
    status: int


@dataclass(frozen=True)
class ReadinessChecks:
    panel_html: bool
    native_v1_capabilities: bool
    anonymous_session_denied_without_cache: bool
    obsolete_native_route_closed: bool
    rauthy_discovery_issuer: bool
    provider_admin_routes_private: bool

    def passed(self) -> bool:
        return all(
            (
                self.panel_html,
                self.native_v1_capabilities,
                self.anonymous_session_denied_without_cache,
                self.obsolete_native_route_closed,
                self.rauthy_discovery_issuer,
                self.provider_admin_routes_private,
            )
        )


@dataclass(frozen=True)
class ReadinessReport:
    checks: ReadinessChecks
    statuses: tuple[ProbeStatus, ...]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: IO[bytes], code: int, msg: str, headers: HTTPMessage, newurl: str
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return


def get_statuses() -> tuple[ProbeReading, ...]:
    """Keep bounded response bytes and security-header flags, never credentials."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    readings: list[ProbeReading] = []
    for path in PATHS:
        request = Request(
            ORIGIN + path,
            headers={
                "Accept": "application/json, text/html",
                "User-Agent": "Briareus-Dev-Native-Readiness/1",
            },
            method="GET",
        )
        try:
            with opener.open(request, timeout=TIMEOUT) as response:
                status = response.status
                content_type = response.headers.get_content_type()
                body = response.read(MAX_BYTES + 1)
                redirected = bool(response.headers.get("location"))
                cache_control = response.headers.get("cache-control", "")
                pragma = response.headers.get("pragma", "")
                sets_cookie = bool(response.headers.get("set-cookie"))
        except HTTPError as error:
            with error:
                status = error.code
                content_type = error.headers.get_content_type()
                body = error.read(MAX_BYTES + 1)
                redirected = bool(error.headers.get("location"))
                cache_control = error.headers.get("cache-control", "")
                pragma = error.headers.get("pragma", "")
                sets_cookie = bool(error.headers.get("set-cookie"))
        except (OSError, HTTPException, URLError):
            readings.append(
                ProbeReading(path, PublicProbe(0, "unavailable", b"", False, "", "", False))
            )
            continue
        probe = PublicProbe(
            status, content_type, body, redirected, cache_control, pragma, sets_cookie
        )
        readings.append(ProbeReading(path, probe))
    return tuple(readings)


def _native_capabilities(probe: PublicProbe) -> bool:
    if not (
        probe.status == 200
        and probe.content_type == "application/json"
        and len(probe.body) <= MAX_BYTES
    ):
        return False
    try:
        document = json.loads(probe.body)
    except (ValueError, TypeError):
        document = None
    if not isinstance(document, dict):
        return False
    return bool(
        document.get("protocol") == "rauthy-native-v1"
        and document.get("first_factor") == "password"
        and document.get("pow") == "client-solved"
        and document.get("cancel") is True
        and isinstance(document.get("continuations"), list)
        and not probe.redirected
    )


def _anonymous_session_denied(probe: PublicProbe) -> bool:
    if not (
        probe.status == 401
        and probe.content_type == "application/json"
        and len(probe.body) <= MAX_BYTES
        and not probe.redirected
        and not probe.sets_cookie
        and probe.cache_control == "no-store"
        and probe.pragma == "no-cache"
    ):
        return False
    try:
        document = json.loads(probe.body)
    except (ValueError, TypeError):
        document = None
    return bool(document == {"error": {"code": "OIDC_SESSION_REQUIRED"}})


def _discovery_issuer(probe: PublicProbe) -> bool:
    if not (
        probe.status == 200
        and probe.content_type == "application/json"
        and len(probe.body) <= MAX_BYTES
    ):
        return False
    try:
        document = json.loads(probe.body)
    except (ValueError, TypeError):
        document = None
    if not isinstance(document, dict):
        return False
    return bool(document.get("issuer") == ISSUER and not probe.redirected)


def review(readings: tuple[ProbeReading, ...]) -> ReadinessReport:
    observed = {reading.path: reading.probe for reading in readings}
    if set(observed) != set(PATHS):
        raise ValueError("missing or extra public readiness probes")
    html = observed["/panel/"]
    capability = observed["/api/v1/auth/capabilities"]
    session = observed["/api/v1/auth/session"]
    obsolete = observed["/api/auth/native/capabilities"]
    oidc = observed["/auth/v1/.well-known/openid-configuration"]
    private = (
        observed["/auth/v1/users"],
        observed["/auth/v1/users/attr"],
        observed["/auth/v1/clients"],
    )
    panel_html = html.status == 200 and html.content_type == "text/html" and not html.redirected
    obsolete_closed = obsolete.status in {404, 410} and not obsolete.redirected
    private_routes = all(value.status == 404 and not value.redirected for value in private)
    checks = ReadinessChecks(
        panel_html=panel_html,
        native_v1_capabilities=_native_capabilities(capability),
        anonymous_session_denied_without_cache=_anonymous_session_denied(session),
        obsolete_native_route_closed=obsolete_closed,
        rauthy_discovery_issuer=_discovery_issuer(oidc),
        provider_admin_routes_private=private_routes,
    )
    return ReadinessReport(
        checks=checks,
        statuses=tuple(ProbeStatus(reading.path, reading.probe.status) for reading in readings),
    )


def main() -> int:
    result = review(get_statuses())
    passed = result.checks.passed()
    output = {
        "scope": "exact public Dev GET only, no redirects, cookies, user credentials or admin APIs",
        "checks": asdict(result.checks),
        "statuses": {entry.path: entry.status for entry in result.statuses},
        "pass": passed,
        "signed_human_user_or_project_authorization_proven": False,
        "native_password_form_visual_acceptance_proven": False,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
