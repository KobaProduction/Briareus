from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock, patch

from control_panel_api.application.services import InvocationAuditService
from control_panel_api.domain.accounts import Account, AuthType, Provider
from control_panel_api.domain.admin_data import AnalysisOverview, FileStats
from control_panel_api.domain.snapshots import (
    CachedSnapshot,
    CoverageSnapshotParameters,
    EmptySnapshotParameters,
    validate_snapshot_contract,
)
from control_panel_api.domain.telemetry import Invocation, InvocationBatch
from control_panel_api.domain.verification import GitHubVerification, SigNozVerification
from control_panel_api.infrastructure.database import CachedSnapshotRecord
from control_panel_api.infrastructure.provider_checks import ProviderConnectionVerifier
from control_panel_api.infrastructure.repositories import SqlAlchemySnapshotRepository
from pydantic import ValidationError


class TypedCoreContracts(unittest.TestCase):
    def test_snapshot_category_rejects_incompatible_parameters_and_payload(self) -> None:
        coverage = CoverageSnapshotParameters(project_id="p", program="a", full=False)
        with self.assertRaises(ValueError):
            validate_snapshot_contract("workspace_stats", coverage, None)
        with self.assertRaises(ValueError):
            validate_snapshot_contract("reverse_coverage", EmptySnapshotParameters(), None)
        with self.assertRaises(ValueError):
            validate_snapshot_contract(
                "workspace_stats", EmptySnapshotParameters(), AnalysisOverview()
            )
        pending = CachedSnapshot("overview", "reverse_overview")
        self.assertIsNone(pending.payload)

    def test_persisted_snapshot_is_decoded_using_its_category(self) -> None:
        record = CachedSnapshotRecord(
            key="overview",
            category="reverse_overview",
            parameters_json="{}",
            payload_json='{"projects": [{"project_id": "p"}], "workers": []}',
            refresh_after_seconds=30,
            status="ready",
            created_at=datetime.now(UTC),
            error_type="",
            error_message="",
        )
        snapshot = SqlAlchemySnapshotRepository._domain(record)
        self.assertIsInstance(snapshot.payload, AnalysisOverview)
        assert isinstance(snapshot.payload, AnalysisOverview)
        self.assertEqual(snapshot.payload.projects[0].project_id, "p")
        for invalid in ('{"projects": "invalid"}', '{"workers": [null]}', "not-json"):
            record.payload_json = invalid
            record.updated_at = datetime.now(UTC)
            record.attempted_at = datetime.now(UTC)
            with self.subTest(payload=invalid):
                snapshot = SqlAlchemySnapshotRepository._domain(record)
                self.assertIsNone(snapshot.payload)
                self.assertEqual(snapshot.status, "pending")
                self.assertIsNone(snapshot.updated_at)
                self.assertIsNone(snapshot.attempted_at)
                self.assertEqual(snapshot.error_type, "SnapshotContractMismatch")
                self.assertNotIn(invalid, snapshot.error_message)
                self.assertEqual(record.payload_json, "{}")
                self.assertEqual(record.status, "pending")
                self.assertIsNone(record.updated_at)
                self.assertIsNone(record.attempted_at)
        record.parameters_json = '{"unexpected": true}'
        with self.assertRaises(ValidationError):
            SqlAlchemySnapshotRepository._domain(record)

    def test_refresh_replaces_invalid_payload_but_rejects_incompatible_new_writes(self) -> None:
        record = CachedSnapshotRecord(
            key="overview",
            category="reverse_overview",
            parameters_json="{}",
            payload_json="malformed-json",
            refresh_after_seconds=30,
            status="ready",
            created_at=datetime.now(UTC),
            error_type="",
            error_message="",
        )
        sessions = MagicMock()
        session = sessions.begin.return_value.__enter__.return_value
        session.get.return_value = record
        repository = SqlAlchemySnapshotRepository(sessions)
        incompatible = FileStats(
            root="/workspace",
            free_bytes=1,
            used_bytes=1,
            total_bytes=2,
            free_display="1 B",
            used_display="1 B",
            total_display="2 B",
            files=0,
            size_bytes=0,
            size_display="0 B",
        )
        with self.assertRaises(ValueError):
            repository.store_success("overview", incompatible)
        self.assertEqual(record.payload_json, "malformed-json")
        expected = AnalysisOverview(projects=[], workers=[])
        snapshot = repository.store_success("overview", expected)
        self.assertEqual(snapshot.payload, expected)
        self.assertEqual(snapshot.status, "ready")
        self.assertEqual(snapshot.error_type, "")
        self.assertIsNotNone(snapshot.updated_at)

    def test_verification_validates_known_identity_fields_at_provider_boundary(self) -> None:
        account = Account(alias="github", provider=Provider.GITHUB, auth_type=AuthType.GITHUB_TOKEN)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"login":"arthur","extra":7}'
        with patch("urllib.request.urlopen", return_value=response):
            result = ProviderConnectionVerifier().verify(account, "token")
        self.assertIsInstance(result, GitHubVerification)
        assert isinstance(result, GitHubVerification)
        self.assertEqual(result.login, "arthur")
        response.__enter__.return_value.read.return_value = b'{"login":123}'
        with (
            patch("urllib.request.urlopen", return_value=response),
            self.assertRaises(ValidationError),
        ):
            ProviderConnectionVerifier().verify(account, "token")

    def test_external_verification_document_preserves_provider_owned_extensions(self) -> None:
        account = Account(
            alias="signoz",
            provider=Provider.SIGNOZ,
            auth_type=AuthType.SIGNOZ_API_KEY,
            base_url="https://signoz.example.test",
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"custom":{"arbitrary":[1,true]}}'
        with patch("urllib.request.urlopen", return_value=response):
            result = ProviderConnectionVerifier().verify(account, "token")
        self.assertIsInstance(result, SigNozVerification)
        assert isinstance(result, SigNozVerification)
        self.assertEqual(result.service_account, {"custom": {"arbitrary": [1, True]}})

    def test_audit_batch_retains_datetime_contract_during_payload_redaction(self) -> None:
        publisher = Mock()
        service = InvocationAuditService(Mock(), publisher=publisher)
        invocation = Invocation(
            module="server", tool="terminal_exec", status="success", duration_ms=1.0
        )
        service.record(invocation)
        batch = publisher.call_args.args[2]
        self.assertIsInstance(batch, InvocationBatch)
        self.assertEqual(batch.events[0].occurred_at, invocation.occurred_at)
        self.assertEqual(batch.count, 1)
