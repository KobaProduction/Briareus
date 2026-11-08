from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from briareus_json_values import JsonObject, JsonValue
from control_panel_api.application.services import SnapshotService
from control_panel_api.domain.snapshots import CachedSnapshot
from control_panel_api.infrastructure.reverse import ReverseAdminClient


class RecordingReverseClient(ReverseAdminClient):
    def __init__(self) -> None:
        self.calls: list[tuple[str, JsonObject]] = []

    async def _call(self, tool: str, arguments: JsonObject | None = None) -> JsonValue:
        values = arguments or {}
        self.calls.append((tool, values))
        if tool == "get_function_count":
            return {"function_count": 10}
        if tool == "list_functions_enhanced":
            return {"functions": [{"address": str(index)} for index in range(10)]}
        if tool == "analyze_function_completeness":
            scores = {"0": 80, "4": 60, "9": 39}
            return {
                "results": [
                    {
                        "effective_score": scores[address],
                        "completeness_score": 50,
                        "has_custom_name": address == "0",
                    }
                    for address in str(values["addresses"]).split(",")
                ]
            }
        return {
            "workers": [None, {"project_id": "z", "worker_index": 2}],
            "projects": [
                None,
                {"project_id": "z", "name": "Z", "path": "/projects/team/z"},
                {"project_id": "a", "name": "A", "path": "/projects/a"},
            ],
        }


class AnalysisStateContracts(unittest.IsolatedAsyncioTestCase):
    async def test_coverage_keeps_even_sampling_batches_and_score_buckets(self) -> None:
        client = RecordingReverseClient()
        report = (
            await client.coverage("project", "program", sample_size=3, batch_size=2)
        ).to_json()
        batches = [
            arguments["addresses"]
            for tool, arguments in client.calls
            if tool == "analyze_function_completeness"
        ]
        self.assertEqual(batches, ["0,4", "9"])
        self.assertTrue(report["approximate"])
        self.assertEqual(report["total_functions"], 10)
        self.assertEqual(report["sample_size"], 3)
        self.assertEqual(report["evaluated_functions"], 3)
        self.assertEqual(report["average_effective_score"], 59.7)
        self.assertEqual(report["complete_80_plus"], 1)
        self.assertEqual(report["strong_60_79"], 1)
        self.assertEqual(report["partial_40_59"], 0)
        self.assertEqual(report["low_under_40"], 1)
        self.assertEqual(report["complete_80_plus_percent"], 33.3)
        self.assertEqual(report["custom_named"], 1)

    async def test_overview_skips_non_objects_and_enriches_project_groups(self) -> None:
        report = (await RecordingReverseClient().overview()).model_dump(
            mode="json", exclude_unset=True
        )
        self.assertEqual(
            report["projects"],
            [
                {
                    "project_id": "a",
                    "name": "A",
                    "path": "/projects/a",
                    "worker_index": None,
                    "group": "Root",
                },
                {
                    "project_id": "z",
                    "name": "Z",
                    "path": "/projects/team/z",
                    "worker_index": 2,
                    "group": "team",
                },
            ],
        )

    def test_snapshot_retries_wait_for_backoff_and_accept_naive_utc_attempts(self) -> None:
        now = datetime.now(UTC)
        recent = CachedSnapshot("recent", "reverse_overview", status="refreshing", attempted_at=now)
        failed = CachedSnapshot("failed", "reverse_overview", status="error", attempted_at=now)
        due = CachedSnapshot(
            "due",
            "reverse_overview",
            status="refreshing",
            attempted_at=(now - timedelta(minutes=1)).replace(tzinfo=None),
        )
        fresh = CachedSnapshot("fresh", "reverse_overview", updated_at=now)
        repository = Mock()
        repository.list_category.return_value = [recent, failed, due, fresh]
        self.assertEqual(SnapshotService(repository).due("reverse_overview"), [due])
        repository.list_category.assert_called_once_with("reverse_overview", limit=100)
