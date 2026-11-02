"""The private Rauthy wire decoder cannot infer identity or provider roles."""

import json
import unittest
from datetime import UTC, datetime, timedelta

from projects.infrastructure.rauthy_protocol import (
    PrivateUserResponse,
    RauthyUserStatusUnavailable,
    decode_user_status,
)


class RauthyProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 10, 21, tzinfo=UTC)
        self.issuer, self.subject = "https://identity.example", "R" * 24
        self.document: dict[str, object] = {"id": self.subject, "enabled": True, "roles": []}

    def response(self) -> PrivateUserResponse:
        return PrivateUserResponse(200, "application/json", json.dumps(self.document).encode())

    def test_only_exact_private_rauthy_admin_role_grants_operator(self) -> None:
        for roles, expected in ((["admin"], "user"), (["rauthy_admin"], "operator"), ([], "user")):
            with self.subTest(roles=roles):
                self.document["roles"] = roles
                self.document["groups"] = ["rauthy_admin"]
                status = decode_user_status(self.response(), self.issuer, self.subject, self.now)
                self.assertEqual(status.role, expected)

    def test_status_cannot_outlive_the_provider_account(self) -> None:
        expiry = self.now + timedelta(seconds=1)
        self.document["user_expires"] = int(expiry.timestamp())
        status = decode_user_status(self.response(), self.issuer, self.subject, self.now)
        self.assertTrue(status.active)
        self.assertEqual(status.expires_at, expiry)
        self.document["user_expires"] = int(self.now.timestamp())
        self.assertFalse(
            decode_user_status(self.response(), self.issuer, self.subject, self.now).active
        )

    def test_subject_and_strict_provider_status_fields_are_required(self) -> None:
        for key, value in (
            ("id", "S" * 24),
            ("enabled", 1),
            ("roles", None),
            ("roles", ["admin", "admin"]),
            ("user_expires", True),
        ):
            with self.subTest(key=key, value=value):
                document = {**self.document, key: value}
                response = PrivateUserResponse(
                    200, "application/json", json.dumps(document).encode()
                )
                with self.assertRaises(RauthyUserStatusUnavailable):
                    decode_user_status(response, self.issuer, self.subject, self.now)

    def test_duplicate_json_keys_cannot_override_identity_or_status(self) -> None:
        response = PrivateUserResponse(
            200,
            "application/json",
            ('{"id":"' + self.subject + '","enabled":false,"enabled":true,"roles":[]}').encode(),
        )
        with self.assertRaises(RauthyUserStatusUnavailable):
            decode_user_status(response, self.issuer, self.subject, self.now)

    def test_not_found_is_disabled_and_bad_display_fields_are_not_authority(self) -> None:
        missing = decode_user_status(
            PrivateUserResponse(404, "", b""), self.issuer, self.subject, self.now
        )
        self.assertFalse(missing.active)
        self.document.update(
            email="person@example.invalid", given_name=13, family_name="unsafe\nname"
        )
        status = decode_user_status(self.response(), self.issuer, self.subject, self.now)
        self.assertEqual(status.name, "person@example.invalid")
        self.assertEqual(status.role, "user")
