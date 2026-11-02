"""Offline public Dev readiness verdict; no network, cookies or credentials."""

from __future__ import annotations

import io
import json
import unittest
from dataclasses import fields
from unittest.mock import patch

import probe_dev_native_auth as probe


def fixture() -> tuple[probe.ProbeReading, ...]:
    cases = {
        path: probe.PublicProbe(404, "application/json", b"{}", False, "no-store", "", False)
        for path in probe.PATHS
    }
    cases["/panel/"] = probe.PublicProbe(200, "text/html", b"<html></html>", False, "", "", False)
    cases["/api/v1/auth/capabilities"] = probe.PublicProbe(
        200,
        "application/json",
        json.dumps(
            {
                "protocol": "rauthy-native-v1",
                "first_factor": "password",
                "pow": "client-solved",
                "cancel": True,
                "continuations": [],
            }
        ).encode(),
        False,
        "no-store",
        "no-cache",
        False,
    )
    cases["/api/v1/auth/session"] = probe.PublicProbe(
        401,
        "application/json",
        b'{"error":{"code":"OIDC_SESSION_REQUIRED"}}',
        False,
        "no-store",
        "no-cache",
        False,
    )
    cases["/auth/v1/.well-known/openid-configuration"] = probe.PublicProbe(
        200,
        "application/json",
        json.dumps({"issuer": probe.ISSUER}).encode(),
        False,
        "no-store",
        "",
        False,
    )
    return tuple(probe.ProbeReading(path, value) for path, value in cases.items())


def changed(path: str, value: probe.PublicProbe) -> tuple[probe.ProbeReading, ...]:
    return tuple(
        probe.ProbeReading(item.path, value) if item.path == path else item for item in fixture()
    )


def observed(path: str) -> probe.PublicProbe:
    return next(item.probe for item in fixture() if item.path == path)


class PublicDevAuthReadinessTests(unittest.TestCase):
    def test_positive_route_security_is_not_real_user_login(self) -> None:
        report = probe.review(fixture())
        self.assertTrue(report.checks.passed())
        self.assertEqual(len(fields(report.checks)), 6)
        output = io.StringIO()
        with (
            patch.object(probe, "get_statuses", return_value=fixture()),
            patch("sys.stdout", output),
        ):
            self.assertEqual(probe.main(), 0)
        document = json.loads(output.getvalue())
        self.assertTrue(document["pass"])
        self.assertFalse(document["signed_human_user_or_project_authorization_proven"])
        self.assertFalse(document["native_password_form_visual_acceptance_proven"])

    def test_old_text_anonymous_401_is_not_accepted(self) -> None:
        path = "/api/v1/auth/session"
        values = changed(
            path,
            observed(path)._replace(
                body=b'{"detail":"OIDC browser session required"}',
            ),
        )
        self.assertFalse(probe.review(values).checks.anonymous_session_denied_without_cache)

    def test_missing_no_store_or_pragma_fails(self) -> None:
        path = "/api/v1/auth/session"
        current = observed(path)
        for value in (current._replace(cache_control=""), current._replace(pragma="")):
            self.assertFalse(probe.review(changed(path, value)).checks.passed())

    def test_browser_cookie_on_anonymous_or_redirect_fails(self) -> None:
        path = "/api/v1/auth/session"
        current = observed(path)
        for value in (
            current._replace(sets_cookie=True),
            current._replace(redirected=True),
            current._replace(status=302),
        ):
            self.assertFalse(
                probe.review(changed(path, value)).checks.anonymous_session_denied_without_cache
            )

    def test_each_admin_rest_path_must_be_gateway_404(self) -> None:
        for path in ("/auth/v1/users", "/auth/v1/users/attr", "/auth/v1/clients"):
            self.assertFalse(
                probe.review(
                    changed(path, observed(path)._replace(status=401))
                ).checks.provider_admin_routes_private
            )

    def test_obsolete_native_return_and_oidc_realm_fail(self) -> None:
        path = "/api/auth/native/capabilities"
        self.assertFalse(
            probe.review(
                changed(path, observed(path)._replace(status=200))
            ).checks.obsolete_native_route_closed
        )
        path = "/auth/v1/.well-known/openid-configuration"
        self.assertFalse(
            probe.review(
                changed(
                    path,
                    observed(path)._replace(
                        body=b'{"issuer":"https://foreign.invalid/auth/v1/"}',
                    ),
                )
            ).checks.rauthy_discovery_issuer
        )

    def test_missing_route_or_oversized_signed_dto_fail(self) -> None:
        values = tuple(item for item in fixture() if item.path != "/auth/v1/clients")
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            probe.review(values)
        path = "/api/v1/auth/capabilities"
        self.assertFalse(
            probe.review(
                changed(
                    path,
                    observed(path)._replace(
                        body=b"x" * (probe.MAX_BYTES + 1),
                    ),
                )
            ).checks.native_v1_capabilities
        )


if __name__ == "__main__":
    unittest.main()
