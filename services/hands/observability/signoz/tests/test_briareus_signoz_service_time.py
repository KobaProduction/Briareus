from __future__ import annotations

import unittest
from unittest.mock import patch

from briareus_account_contracts import ResolvedAccount
from briareus_signoz.client import SigNozClient, _service_timestamp_ns


class SigNozServiceTimeContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.client = SigNozClient(
            ResolvedAccount(
                id="source-id",
                alias="telemetry",
                provider="signoz",
                auth_type="api_key",
                base_url="https://telemetry.example.test",
                credential="test-only",
                created_at="created",
                updated_at="revision",
            )
        )

    def test_iso_offsets_and_unix_units_normalize_to_nanoseconds(self) -> None:
        expected = "1794355200000000000"
        for value in (
            "2026-11-11T00:00:00Z",
            "2026-11-11T01:00:00+01:00",
            "1794355200",
            "1794355200000",
            "1794355200000000",
            expected,
        ):
            with self.subTest(value=value):
                self.assertEqual(_service_timestamp_ns(value), expected)

    def test_preserves_subsecond_precision(self) -> None:
        self.assertEqual(
            _service_timestamp_ns("2026-11-11T00:00:00.123456Z"),
            "1794355200123456000",
        )

    def test_invalid_or_reversed_ranges_never_call_provider(self) -> None:
        with patch.object(self.client, "_request") as request:
            for value in ("2026-11-11", "bad", "17943552000", "0", ""):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    self.client.list_services(start=value, end="2026-11-12T00:00:00Z")
            with self.assertRaisesRegex(ValueError, "end after start"):
                self.client.list_services(
                    start="2026-11-12T00:00:00Z",
                    end="2026-11-11T00:00:00Z",
                )
            request.assert_not_called()

    def test_list_services_sends_normalized_strings_to_provider(self) -> None:
        with patch.object(self.client, "_request", return_value={"data": []}) as request:
            result = self.client.list_services(
                start="2026-11-11T00:00:00Z",
                end="1794441600000",
            )
        self.assertEqual(result, {"data": []})
        request.assert_called_once_with(
            "POST",
            "/api/v1/services",
            payload={"start": "1794355200000000000", "end": "1794441600000000000"},
        )
