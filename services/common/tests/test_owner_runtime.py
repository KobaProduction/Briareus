"""Fresh owner authority and owner-scoped lifecycle without a database or HTTP server."""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from common.application.owner_ingress import AttestOwnerIngress
from common.application.owner_startup import OwnerNotReady, OwnerSchemaStatus, OwnerStartup
from common.domain.owner_runtime import VerifiedOwnerIngress, permits_local_schema_status
from common.owner_startup_diagnostics import Phase

NOW = datetime(2026, 10, 21, tzinfo=UTC)
VALID = VerifiedOwnerIngress("resources", "unix-peer", True, NOW + timedelta(seconds=3))


def fixed_now() -> datetime:
    return NOW


@dataclass
class Ingress:
    fact: VerifiedOwnerIngress = VALID
    calls: int = 0

    async def verify_running_ingress(self) -> VerifiedOwnerIngress:
        self.calls += 1
        return self.fact


@dataclass
class Schema:
    available: bool = True
    events: list[str] = field(default_factory=list)
    fail_verification: bool = False

    def initialize(self, phase_change: Callable[[Phase], None]) -> None:
        self.events.append("initialize")
        phase_change("db_create")

    async def migrate(self, phase_change: Callable[[Phase], None]) -> None:
        self.events.append("migrate")
        phase_change("migration_lock")

    async def verify(self, *, fresh_settings: bool = False) -> OwnerSchemaStatus:
        self.events.append("verify_fresh" if fresh_settings else "verify")
        if self.fail_verification:
            raise RuntimeError("provider diagnostic must remain private")
        return OwnerSchemaStatus("reviewed", 7)

    async def close(self) -> None:
        self.events.append("close")


class OwnerIngressTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_attestation_rejects_revoked_transport_owner_signer_or_expiry(self) -> None:
        ingress = Ingress()
        attest = AttestOwnerIngress("resources", ingress, fixed_now)
        self.assertTrue(await attest.execute())
        rejected = (
            replace(VALID, owner="platform"),
            replace(VALID, authenticated_transport="header"),
            replace(VALID, signer_present=False),
            replace(VALID, expires_at=NOW),
            replace(VALID, expires_at=NOW.replace(tzinfo=None)),
        )
        for fact in rejected:
            ingress.fact = fact
            self.assertFalse(await attest.execute())
        self.assertEqual(ingress.calls, 6)

    async def test_absent_verifier_fails_closed(self) -> None:
        self.assertFalse(await AttestOwnerIngress("resources", None, fixed_now).execute())

    async def test_timeout_is_three_seconds_and_cancellation_propagates(self) -> None:
        class StalledIngress:
            async def verify_running_ingress(self) -> VerifiedOwnerIngress:
                await asyncio.Event().wait()
                return VALID

        original_timeout = asyncio.timeout
        with patch(
            "common.application.owner_ingress.asyncio.timeout",
            side_effect=lambda _delay: original_timeout(0),
        ) as timeout:
            self.assertFalse(
                await AttestOwnerIngress("resources", StalledIngress(), fixed_now).execute()
            )
        timeout.assert_called_once_with(3)

        class CancelledIngress:
            async def verify_running_ingress(self) -> VerifiedOwnerIngress:
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await AttestOwnerIngress("resources", CancelledIngress(), fixed_now).execute()


class OwnerStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_then_ingress_and_fresh_readiness(self) -> None:
        schema, ingress = Schema(), Ingress()
        startup = OwnerStartup(
            "resources", schema, AttestOwnerIngress("resources", ingress, fixed_now)
        )
        await startup.start()
        self.assertEqual(schema.events, ["initialize", "migrate", "verify"])
        self.assertEqual(startup.status.state, "ready")
        self.assertEqual(startup.status.revision, "reviewed")
        self.assertEqual(startup.status.table_count, 7)
        self.assertTrue((await startup.require_ready()).security_ready)
        self.assertEqual(schema.events[-1], "verify_fresh")
        self.assertEqual(ingress.calls, 2)
        await startup.close()
        self.assertEqual(startup.status.state, "stopped")
        self.assertEqual(schema.events[-1], "close")

    async def test_absent_ingress_stays_pending_and_bad_ingress_denies_startup(self) -> None:
        startup = OwnerStartup(
            "resources", Schema(), AttestOwnerIngress("resources", None, fixed_now)
        )
        await startup.start()
        self.assertEqual(startup.status.state, "security_pending")
        with self.assertRaisesRegex(OwnerNotReady, "authoritative owner not ready"):
            await startup.require_ready()
        startup = OwnerStartup(
            "resources",
            Schema(),
            AttestOwnerIngress(
                "resources", Ingress(replace(VALID, signer_present=False)), fixed_now
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "owner ingress trust attestation denied"):
            await startup.start()
        self.assertEqual(startup.phase, "ingress_attestation")

    async def test_readiness_revocation_or_schema_failure_exposes_fixed_reason(self) -> None:
        schema, ingress = Schema(), Ingress()
        startup = OwnerStartup(
            "resources", schema, AttestOwnerIngress("resources", ingress, fixed_now)
        )
        await startup.start()
        ingress.fact = replace(VALID, expires_at=NOW)
        with self.assertRaisesRegex(OwnerNotReady, "schema or ingress unavailable"):
            await startup.require_ready()
        self.assertEqual(schema.events, ["initialize", "migrate", "verify"])
        ingress.fact = VALID
        schema.fail_verification = True
        with self.assertRaisesRegex(OwnerNotReady, "schema or ingress unavailable"):
            await startup.require_ready()


class LocalSchemaVisibilityTests(unittest.TestCase):
    def test_two_loopback_socket_ends_required_without_forwarding(self) -> None:
        cases = (
            ("127.0.0.1", "::1", False, True),
            ("::1", "127.0.0.1", False, True),
            ("127.0.0.1", "0:0:0:0:0:0:0:0", False, False),
            ("192.0.2.1", "127.0.0.1", False, False),
            ("127.0.0.1", "127.0.0.1", True, False),
            ("localhost", "127.0.0.1", False, False),
            ("127.0.0.1", "", False, False),
        )
        for origin, server_host, forwarded, expected in cases:
            with self.subTest(origin=origin, server_host=server_host, forwarded=forwarded):
                self.assertEqual(
                    permits_local_schema_status(
                        origin=origin, server_host=server_host, forwarded=forwarded
                    ),
                    expected,
                )
