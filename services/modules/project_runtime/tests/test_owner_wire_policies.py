"""Exact legacy owner preimages never enable incomplete external-effect lifecycles."""

import unittest
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import NAMESPACE_DNS, uuid4, uuid5

from pydantic import BaseModel

from modules.analysis.a6_native import NativeImportTransition
from modules.files.a6_signed import FilesReserve, FilesTransition, path_fingerprint
from modules.project_runtime.a6_runtime import RuntimeLeaseCommand, RuntimeOpenCommand
from modules.project_runtime.catalog_owner import CatalogListRequest
from modules.project_runtime.owner_authorization import VerifiedOwnerRecipient
from modules.project_runtime.owner_wire import (
    A11EffectOwner,
    A11OwnerWireNotAccepted,
    accepted_a11_owner_wire,
    require_accepted_owner_lifecycle,
)


def recipient() -> VerifiedOwnerRecipient:
    return VerifiedOwnerRecipient(
        uuid4(), uuid4(), datetime.now(UTC) + timedelta(seconds=5), "mtls"
    )


def reservation() -> FilesReserve:
    return FilesReserve(
        operation_uuid=uuid4(),
        destination="fixture/new.bin",
        maximum_bytes=8,
        expected_sha256="a" * 64,
        expected_file_version=0,
        project_access_revision="b" * 64,
        idempotency_key="fixture",
    )


def transition(phase: Literal["dispatch", "release", "unknown"]) -> FilesTransition:
    return FilesTransition(
        operation_uuid=uuid4(),
        reservation_id=uuid4(),
        expected_version=2,
        destination="fixture/new.bin",
        phase=phase,
    )


class OwnerWirePolicyTests(unittest.TestCase):
    def test_all_incomplete_owner_lifecycles_still_deny(self) -> None:
        owners: tuple[A11EffectOwner, ...] = ("catalog", "files", "execution", "reverse")
        for owner in owners:
            with self.subTest(owner=owner), self.assertRaises(A11OwnerWireNotAccepted) as raised:
                require_accepted_owner_lifecycle(owner)
            self.assertEqual(
                raised.exception.code, "A12_OWNER_COMPLETE_SIGNED_EFFECT_LIFECYCLE_REQUIRED"
            )

    def test_reservation_keeps_exact_signed_business_preimage(self) -> None:
        peer, command = recipient(), reservation()
        wire = accepted_a11_owner_wire("files", "reserve", command, peer=peer)
        self.assertEqual(wire.operation, "files.write.reserve")
        self.assertEqual(
            wire.business_payload.model_dump(mode="json"),
            {
                "service_id": str(peer.service_id),
                "instance_uuid": str(peer.instance_uuid),
                "path_digest": path_fingerprint(command.destination),
                "content_sha256": command.expected_sha256,
                "planned_bytes": 8,
                "expected_file_version": 0,
                "ttl_seconds": 600,
            },
        )

    def test_overwrite_or_unaccepted_size_deny(self) -> None:
        command, peer = reservation(), recipient()
        for invalid in (
            command.model_copy(update={"expected_file_version": 1}),
            command.model_copy(update={"maximum_bytes": 262145}),
        ):
            with (
                self.subTest(invalid=invalid),
                self.assertRaises(A11OwnerWireNotAccepted) as raised,
            ):
                accepted_a11_owner_wire("files", "reserve", invalid, peer=peer)
            self.assertEqual(raised.exception.code, "A11_FILES_UNAPPROVED_OVERWRITE_OR_SIZE")

    def test_dispatch_and_candidate_transition_keep_distinct_preimage_keys(self) -> None:
        peer, command = recipient(), transition("dispatch")
        dispatched = accepted_a11_owner_wire("files", "dispatch", command, peer=peer)
        self.assertEqual(
            dispatched.business_payload.model_dump(mode="json")["reservation_operation_uuid"],
            str(command.operation_uuid),
        )
        self.assertEqual(
            dispatched.business_payload.model_dump(mode="json")["expected_reservation_version"], 2
        )
        released = accepted_a11_owner_wire(
            "files", "release", command.model_copy(update={"phase": "release"}), peer=peer
        )
        self.assertEqual(
            released.business_payload.model_dump(mode="json")["original_operation_uuid"],
            str(command.operation_uuid),
        )
        self.assertEqual(released.business_payload.model_dump(mode="json")["expected_version"], 2)
        self.assertNotIn(
            "reservation_operation_uuid", released.business_payload.model_dump(mode="json")
        )
        with self.assertRaises(A11OwnerWireNotAccepted) as raised:
            accepted_a11_owner_wire("files", "dispatch", transition("release"), peer=peer)
        self.assertEqual(raised.exception.code, "A11_FILES_DISPATCH_PHASE_MISMATCH")

    def test_runtime_open_requires_exact_instance_and_keeps_ttl_fields(self) -> None:
        peer = recipient()
        command = RuntimeOpenCommand(
            operation_uuid=uuid4(),
            runtime_session_uuid=uuid4(),
            instance_uuid=peer.instance_uuid,
            kind="terminal",
            idle_seconds=30,
            hard_seconds=60,
            idempotency_key="fixture",
        )
        wire = accepted_a11_owner_wire("execution", "open", command, peer=peer)
        self.assertEqual(wire.operation, "runtime.session.open")
        self.assertEqual(wire.business_payload.model_dump(mode="json")["idle_ttl_seconds"], 30)
        with self.assertRaises(A11OwnerWireNotAccepted) as raised:
            accepted_a11_owner_wire(
                "execution",
                "open",
                command.model_copy(update={"instance_uuid": uuid4()}),
                peer=peer,
            )
        self.assertEqual(raised.exception.code, "A11_RUNTIME_OWNER_INSTANCE_MISMATCH")

    def test_runtime_renew_has_nonce_but_revoke_preserves_original_abi_without_it(self) -> None:
        peer = recipient()
        command = RuntimeLeaseCommand(
            operation_uuid=uuid4(),
            runtime_session_uuid=uuid4(),
            expected_version=2,
            lease_nonce=uuid4(),
            phase="heartbeat",
        )
        renew = accepted_a11_owner_wire("execution", "heartbeat", command, peer=peer)
        self.assertEqual(
            renew.business_payload.model_dump(mode="json")["expected_lease_nonce"],
            str(command.lease_nonce),
        )
        revoke = accepted_a11_owner_wire(
            "execution", "revoke", command.model_copy(update={"phase": "revoke"}), peer=peer
        )
        self.assertNotIn("expected_lease_nonce", revoke.business_payload.model_dump(mode="json"))
        with self.assertRaises(A11OwnerWireNotAccepted):
            accepted_a11_owner_wire("execution", "revoke", command, peer=peer)

    def test_native_transition_rejects_phase_substitution_and_keeps_original_operation(
        self,
    ) -> None:
        peer = recipient()
        command = NativeImportTransition(
            operation_uuid=uuid4(), import_uuid=uuid4(), expected_version=2, phase="dispatch"
        )
        wire = accepted_a11_owner_wire("reverse", "dispatch", command, peer=peer)
        self.assertEqual(
            wire.business_payload.model_dump(mode="json")["original_operation_uuid"],
            str(command.operation_uuid),
        )
        self.assertEqual(
            wire.business_payload.model_dump(mode="json")["expected_import_version"], 2
        )
        unknown = accepted_a11_owner_wire(
            "reverse", "mark_unknown", command.model_copy(update={"phase": "unknown"}), peer=peer
        )
        self.assertEqual(unknown.business_payload.model_dump(mode="json")["expected_version"], 2)
        with self.assertRaises(A11OwnerWireNotAccepted):
            accepted_a11_owner_wire("reverse", "cancel", command, peer=peer)

    def test_catalog_read_cannot_become_credential_redemption(self) -> None:
        peer = recipient()
        command = CatalogListRequest(
            project_id=uuid4(), kind="integration", expected_control_revision="a" * 64
        )
        wire = accepted_a11_owner_wire("catalog", "read", command, peer=peer)
        self.assertEqual(wire.operation, "catalog.integrations.list")
        self.assertEqual(
            wire.business_payload.model_dump(mode="json"),
            {"kind": "integrations", "scope": "all", "alias_key": None, "limit": 100},
        )
        with self.assertRaises(A11OwnerWireNotAccepted):
            accepted_a11_owner_wire("catalog", "redeem", command, peer=peer)

    def test_nominal_peer_and_typed_payload_are_required_before_mapping(self) -> None:
        command, peer = reservation(), recipient()
        invalid_peer = VerifiedOwnerRecipient(
            uuid5(NAMESPACE_DNS, "fixture"), peer.instance_uuid, peer.expires_at, peer.transport
        )
        with self.assertRaises(A11OwnerWireNotAccepted):
            accepted_a11_owner_wire("files", "reserve", command, peer=invalid_peer)
        with self.assertRaises(A11OwnerWireNotAccepted):
            accepted_a11_owner_wire("files", "reserve", cast(BaseModel, {}), peer=peer)
