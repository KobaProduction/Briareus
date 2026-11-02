"""One current account lease cannot leak credentials or resolve an ambiguous identity."""

import json
import unittest
from uuid import UUID

from hand_runtime.account_lease import InvocationAccounts
from node_protocol.provider_context import ProjectAccount


def account() -> ProjectAccount:
    return ProjectAccount(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        alias="selected",
        provider="github",
        auth_type="github_token",
        base_url="https://api.github.com",
        enabled=True,
        created_at="",
        updated_at="",
        external_id=None,
        ca_cert_pem=None,
        credential="fixture-private-token",
    )


class AccountLeaseTests(unittest.TestCase):
    def test_public_metadata_excludes_private_credential(self) -> None:
        row = account()
        lease = InvocationAccounts([row])
        listed = lease.list_accounts()
        self.assertEqual(listed.count, 1)
        self.assertEqual(listed.accounts[0].id, str(row.id))
        assert row.credential is not None
        self.assertNotIn(row.credential, json.dumps(listed.model_dump()))
        self.assertEqual(lease.resolve_account("SELECTED", provider="github").id, str(row.id))
        lease.clear()
        with self.assertRaises(ValueError):
            lease.resolve_account("selected", provider="github")

    def test_disabled_duplicate_and_oversized_leases_fail(self) -> None:
        row = account()
        invalid = ([row, row], [row] * 65)
        for values in invalid:
            with self.subTest(values=type(values[0]).__name__), self.assertRaises(ValueError):
                InvocationAccounts(values)
        for wire in (
            row.model_dump_json().replace('"enabled":true', '"enabled":false'),
            '"not-account-metadata"',
        ):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                ProjectAccount.model_validate_json(wire)

    def test_public_metadata_cannot_authorize_effect(self) -> None:
        row = account()
        public = ProjectAccount.model_validate_json(row.model_dump_json(exclude={"credential"}))
        lease = InvocationAccounts([public])
        self.assertEqual(lease.list_accounts(provider="github").count, 1)
        with self.assertRaisesRegex(ValueError, "private credential"):
            lease.resolve_account("selected", provider="github")

    def test_alias_ambiguity_and_cross_provider_fail_closed(self) -> None:
        row = account()
        second = ProjectAccount.model_validate_json(
            row.model_dump_json()
            .replace(str(row.id), "22222222-2222-4222-8222-222222222222")
            .replace('"selected"', '"SELECTED"')
        )
        lease = InvocationAccounts([row, second])
        for selector, provider in (
            ("selected", "github"),
            (str(row.id), "gitlab"),
            (" ", "github"),
        ):
            with self.subTest(selector=selector, provider=provider), self.assertRaises(ValueError):
                lease.resolve_account(selector, provider=provider)
        self.assertEqual(lease.resolve_account(str(row.id), provider="github").id, str(row.id))
