"""Fail-closed, no-network invariants of the Dev owner read-only inventory."""

from __future__ import annotations

import os
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import dev_owner_db_readonly_inventory as inventory


@contextmanager
def _environment(
    owner: str = "platform",
    *,
    database: str | None = None,
    host: str = "briareus-postgres",
    port: str = "5432",
    user: str = "briareus_fixture",
    password: str | None = None,
) -> Iterator[None]:
    with patch.dict(
        os.environ,
        {
            "POSTGRES_HOST": host,
            "POSTGRES_PORT": port,
            "POSTGRES_DB": database if database is not None else inventory._OWNERS[owner],
            "POSTGRES_USER": user,
            "POSTGRES_PASSWORD": "fixture-only-no-real-credential"
            if password is None
            else password,
        },
        clear=True,
    ):
        yield


class ScopedDevOwnerInventoryContractTests(unittest.TestCase):
    def test_three_exact_allowed_owner_names(self) -> None:
        self.assertEqual(
            inventory._OWNERS,
            {
                "access": "briareus_access",
                "platform": "briareus_platform",
                "resources": "briareus_resources",
            },
        )
        self.assertNotIn("briareus_rauthy", inventory._OWNERS.values())
        self.assertNotIn("briareus_files", inventory._OWNERS.values())

    def test_valid_existing_application_postgres_env_without_any_new_key(self) -> None:
        with _environment():
            self.assertEqual(inventory._connection_contract("platform")[0], "briareus_fixture")

    def test_foreign_database_and_provider_database_fail_closed(self) -> None:
        for target in ("briareus_rauthy", "briareus_files", "briareus_identity", "briareus_dev"):
            with _environment(database=target), self.assertRaises(ValueError):
                inventory._connection_contract("platform")

    def test_wrong_port_or_host_fails_before_connect(self) -> None:
        for host in ("127.0.0.1", "other-project-postgres"):
            with _environment(host=host), self.assertRaises(ValueError):
                inventory._connection_contract("platform")
        with _environment(port="5433"), self.assertRaises(ValueError):
            inventory._connection_contract("platform")

    def test_empty_secret_or_bad_user_rejected(self) -> None:
        with _environment(password=""), self.assertRaises(ValueError):
            inventory._connection_contract("platform")
        with _environment(user="name;rm"), self.assertRaises(ValueError):
            inventory._connection_contract("platform")

    def test_unknown_owner_rejected_before_connection(self) -> None:
        with _environment():
            for owner in ("rauthy", "files", "identity", "runtime"):
                with self.assertRaises(ValueError):
                    inventory._connection_contract(owner)


def _identity_field(key: str) -> str:
    if key == "db":
        return "briareus_platform"
    if key == "role":
        return "briareus_fixture"
    raise KeyError(key)


class ReadonlySqlOwnerProofTests(unittest.IsolatedAsyncioTestCase):
    async def test_foreign_owned_database_denied_before_any_table_content(self) -> None:
        identity = MagicMock(spec=("__getitem__",))
        identity.__getitem__.side_effect = _identity_field
        connection = Mock(spec=("transaction", "fetchrow", "fetchval", "fetch"))
        transaction = AsyncMock()
        connection.transaction.return_value = transaction
        connection.fetchrow = AsyncMock(return_value=identity)
        connection.fetchval = AsyncMock(return_value="unrelated_postgres_role")
        connection.fetch = AsyncMock()
        with self.assertRaisesRegex(ValueError, "foreign PostgreSQL owner"):
            await inventory.inspect_connection(connection, "platform", "briareus_fixture")
        connection.transaction.assert_called_once_with(isolation="repeatable_read", readonly=True)
        connection.fetchrow.assert_awaited_once_with(
            "SELECT current_database() AS db, current_user AS role"
        )
        connection.fetchval.assert_awaited_once_with(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()"
        )
        connection.fetch.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
