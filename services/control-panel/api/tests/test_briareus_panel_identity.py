from __future__ import annotations

import time
import unittest
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from briareus_support import ISSUER, ORIGIN, SUBJECT, IdentityHarness
from control_panel_api.application.identity import IdentityFlowError, pkce_challenge
from control_panel_api.domain.identity import PANEL_SESSION_KEY
from control_panel_api.infrastructure.identity_sessions import SqlIdentitySessionRepository
from control_panel_api.presentation.identity import build_identity_router
from fastapi import FastAPI
from sqlalchemy import event, select, text
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient


class PanelIdentityContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = IdentityHarness()
        self.addCleanup(self.harness.close)

    def test_login_state_is_one_use_and_bound_to_the_initiating_browser(self) -> None:
        start = self.harness.service.begin()
        with self.assertRaises(IdentityFlowError):
            self.harness.service.complete(cookie_state="other-browser", state=start.state, code="c")
        self.assertEqual(self.harness.provider.exchanges, 0)
        session = self.harness.service.complete(
            cookie_state=start.state,
            state=start.state,
            code="c",
        )
        self.assertEqual(session.grant.subject, SUBJECT)
        with self.assertRaises(IdentityFlowError):
            self.harness.service.complete(cookie_state=start.state, state=start.state, code="c")
        self.assertEqual(self.harness.provider.exchanges, 1)

    def test_expired_transaction_cannot_exchange_a_code(self) -> None:
        start = self.harness.service.begin()
        transaction = self.harness.repository.consume_transaction(start.state)
        self.assertIsNotNone(transaction)
        assert transaction is not None
        self.harness.repository.put_transaction(replace(transaction, expires_at=0))
        with self.assertRaises(IdentityFlowError):
            self.harness.service.complete(cookie_state=start.state, state=start.state, code="c")
        self.assertEqual(self.harness.provider.exchanges, 0)

    def test_pkce_uses_the_standard_s256_challenge(self) -> None:
        self.assertEqual(
            pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        )
        start = self.harness.service.begin()
        query = parse_qs(urlsplit(start.url).query)
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertTrue(query["nonce"][0])

    def test_only_current_provider_identity_can_create_a_session(self) -> None:
        invalid_grants = (
            replace(self.harness.provider.grant, issuer="https://another.example.test"),
            replace(self.harness.provider.grant, subject="unappointed-user"),
            replace(self.harness.provider.grant, expires_at=int(time.time()) - 1),
        )
        for grant in invalid_grants:
            with self.subTest(issuer=grant.issuer, subject=grant.subject):
                self.harness.provider.grant = grant
                start = self.harness.service.begin()
                with self.assertRaises(IdentityFlowError):
                    self.harness.service.complete(
                        cookie_state=start.state,
                        state=start.state,
                        code="c",
                    )

    def test_durable_session_rejects_expiry_and_a_removed_subject(self) -> None:
        identifier = self.harness.authenticate()
        self.harness.expire(identifier)
        self.assertIsNone(self.harness.service.current(identifier))
        self.assertIsNone(self.harness.repository.get_session(identifier))
        identifier = self.harness.authenticate()
        self.harness.service.allowed_subjects = ()
        self.assertIsNone(self.harness.service.current(identifier))

    def test_logout_revokes_local_authority_even_when_provider_is_unavailable(self) -> None:
        identifier = self.harness.authenticate()
        session = self.harness.service.current(identifier)
        assert session is not None
        self.harness.provider.logout_error = True
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.harness.service.logout(session)
        self.assertIsNone(self.harness.service.current(identifier))

    def test_session_tokens_are_encrypted_and_do_not_replace_existing_owner_tables(self) -> None:
        with self.harness.engine.begin() as connection:
            connection.execute(text("CREATE TABLE existing_audit (event TEXT NOT NULL)"))
            connection.execute(text("INSERT INTO existing_audit VALUES ('keep-me')"))
        statements: list[str] = []

        def capture(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: bool,
        ) -> None:
            statements.append(statement)

        event.listen(self.harness.engine, "before_cursor_execute", capture)
        try:
            SqlIdentitySessionRepository(self.harness.engine, self.harness.cipher)
        finally:
            event.remove(self.harness.engine, "before_cursor_execute", capture)
        self.assertEqual(statements, [])
        identifier = self.harness.authenticate()
        with self.harness.engine.connect() as connection:
            payload = connection.execute(
                select(self.harness.repository.sessions.c.payload)
            ).scalar_one()
            audit = connection.execute(text("SELECT event FROM existing_audit")).scalar_one()
        self.assertEqual(audit, "keep-me")
        for value in (SUBJECT, "test-access-token", "test-id-token", "test-refresh-token"):
            self.assertNotIn(value, payload)
        restored = self.harness.repository.get_session(identifier)
        assert restored is not None
        self.assertEqual(restored.grant.issuer, ISSUER)


class PanelHttpIdentityContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = IdentityHarness()
        self.addCleanup(self.harness.close)
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-cookie-signing-key")
        app.include_router(build_identity_router(self.harness.service, ORIGIN))
        self.client = TestClient(app, base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def login(self) -> tuple[str, str]:
        response = self.client.get("/admin/api/auth/login", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
        callback = self.client.get(
            "/admin/api/auth/callback",
            params={"state": state, "code": "code"},
            follow_redirects=False,
        )
        self.assertEqual(callback.status_code, 303)
        body = self.client.get("/admin/api/session").json()
        self.assertTrue(body["authenticated"])
        return str(body["subject"]), str(body["csrf_token"])

    def test_server_session_is_required_and_legacy_cookie_does_not_authorize(self) -> None:
        self.assertFalse(self.client.get("/admin/api/session").json()["authenticated"])
        self.client.cookies.set("management_admin", "administrator")
        self.assertFalse(self.client.get("/admin/api/session").json()["authenticated"])
        subject, csrf = self.login()
        self.assertEqual(subject, SUBJECT)
        self.assertTrue(csrf)
        self.assertNotIn(PANEL_SESSION_KEY, self.client.get("/admin/api/session").text)

    def test_logout_requires_both_exact_origin_and_current_csrf(self) -> None:
        _, csrf = self.login()
        for headers in (
            {},
            {"Origin": ORIGIN},
            {"Origin": "https://evil.example", "X-CSRF-Token": csrf},
        ):
            with self.subTest(headers=headers):
                self.assertEqual(
                    self.client.post("/admin/api/logout", headers=headers).status_code, 403
                )
        response = self.client.post(
            "/admin/api/logout",
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.client.get("/admin/api/session").json()["authenticated"])
        self.assertEqual(self.client.post("/admin/api/logout").status_code, 401)

    def test_callback_from_another_browser_or_a_replayed_callback_is_rejected(self) -> None:
        response = self.client.get("/admin/api/auth/login", follow_redirects=False)
        state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
        with TestClient(self.client.app, base_url=ORIGIN) as other:
            self.assertEqual(
                other.get(
                    "/admin/api/auth/callback",
                    params={"state": state, "code": "code"},
                ).status_code,
                401,
            )
        self.assertEqual(
            self.client.get(
                "/admin/api/auth/callback",
                params={"state": state, "code": "code"},
                follow_redirects=False,
            ).status_code,
            303,
        )
        self.assertEqual(
            self.client.get(
                "/admin/api/auth/callback",
                params={"state": state, "code": "code"},
            ).status_code,
            401,
        )
