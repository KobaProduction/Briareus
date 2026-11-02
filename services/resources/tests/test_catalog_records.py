"""Persistence compatibility and definition parsing fail closed on unreviewed input."""

import json
import unittest
from dataclasses import replace
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from projects.domain.module_catalog import CatalogError, Publication, PublicationReceipt
from projects.infrastructure.catalog_records import InputPayload, artifact_definition, stored_inputs
from projects.infrastructure.module_catalog import SqlCatalogSession
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from node_protocol.catalog import ARTIFACTS


class CatalogRecordsTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_encrypted_receipt_remains_readable_without_rewriting_it(self) -> None:
        cipher = Fernet(Fernet.generate_key())
        identifier = str(uuid4())
        original = {
            "fingerprint": "a" * 64,
            "result": {
                "release": {
                    "id": identifier,
                    "module": "files",
                    "source_commit": "b" * 40,
                    "input_fingerprint": "c" * 64,
                    "image": "registry.example/files@sha256:" + "d" * 64,
                    "platform": "linux/amd64",
                    "state": "published",
                    "created_at": "2026-10-21T12:34:56+00:00",
                }
            },
        }
        token = cipher.encrypt(json.dumps(original).encode()).decode()
        receipt = PublicationReceipt(str(uuid4()), str(uuid4()), "a" * 64, "completed", token)
        async with AsyncSession() as session:
            replay = SqlCatalogSession(session, cipher).replay(receipt)
        self.assertEqual(replay.fingerprint, original["fingerprint"])
        self.assertEqual(replay.result.release.id, identifier)
        self.assertEqual(replay.result.release.created_at, "2026-10-21T12:34:56+00:00")
        self.assertEqual(receipt.encrypted_outcome, token)

    def test_unrecognized_json_fields_and_explicit_null_build_args_are_not_approved(self) -> None:
        payload = InputPayload.from_record(artifact_definition(ARTIFACTS["files"]).inputs)
        with_extra = payload.model_dump(mode="json", exclude_none=True)
        with_extra["unreviewed"] = True
        with self.assertRaises(ValidationError):
            InputPayload.model_validate(with_extra)
        with self.assertRaises(ValidationError):
            InputPayload.model_validate(payload.model_dump(mode="json"))
        self.assertEqual(
            stored_inputs(
                InputPayload.model_validate(payload.model_dump(mode="json", exclude_none=True))
            ),
            payload.record(),
        )

    def test_build_argument_order_is_not_a_definition_change(self) -> None:
        definition = artifact_definition(ARTIFACTS["reverse"])
        payload = InputPayload.from_record(definition.inputs)
        self.assertIsNotNone(payload.build_args)
        arguments = (
            {} if payload.build_args is None else dict(reversed(tuple(payload.build_args.items())))
        )
        reversed_payload = payload.model_copy(update={"build_args": arguments})
        self.assertEqual(stored_inputs(reversed_payload), definition.inputs)

    def test_publication_rejects_invalid_immutable_identity_without_a_wire_model(self) -> None:
        publication = Publication(
            uuid4(),
            "files",
            "a" * 40,
            "b" * 64,
            "registry.example/files@sha256:" + "c" * 64,
            "linux/amd64",
        )
        for changes in (
            {"id": UUID(int=0)},
            {"source_commit": "bad"},
            {"input_fingerprint": "bad"},
            {"image": "registry.example/files:latest"},
            {"platform": "other"},
        ):
            with self.subTest(changes=changes), self.assertRaises(CatalogError):
                replace(publication, **changes)
