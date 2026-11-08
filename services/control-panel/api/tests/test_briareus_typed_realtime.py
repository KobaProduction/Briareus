from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from briareus_cache.settings import ValkeySettings
from briareus_json_values import StrictModel
from control_panel_api.realtime import RealtimeBus, RealtimeEnvelope, RealtimeFanout
from control_panel_api.realtime_api import RealtimeCommand
from pydantic import ValidationError


class StatusPayload(StrictModel):
    available: bool
    optional_detail: str | None = None


class TypedRealtimeContracts(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cache = Mock()
        self.cache.key.side_effect = lambda *parts: ":".join(parts)
        with patch("valkey.Valkey.from_url"):
            self.bus = RealtimeBus(self.cache, ValkeySettings())

    async def test_typed_event_survives_cache_and_fanout_without_adding_optional_fields(
        self,
    ) -> None:
        subscriber = self.bus.register()
        subscriber.topics.add("browser.runtime")
        event = await self.bus.publish("browser.runtime", "state", StatusPayload(available=True))
        self.assertEqual(event.data, {"available": True})
        self.assertIs(await subscriber.queue.get(), event)
        self.cache.get_json.return_value = event.to_json()
        self.assertEqual(self.bus.snapshot("browser.runtime"), event)
        remote = RealtimeFanout(source="another-api", event=event)
        self.bus._receive_message({"data": remote.model_dump_json()})
        self.assertEqual(await subscriber.queue.get(), event)

    async def test_invalid_fanout_cannot_enter_subscriber_queue(self) -> None:
        subscriber = self.bus.register()
        subscriber.topics.add("browser.runtime")
        self.bus._receive_message({"data": '{"source":"other","event":{"topic":"other"}}'})
        self.assertTrue(subscriber.queue.empty())
        with self.assertRaises(ValidationError):
            RealtimeEnvelope.create("unrecognized", "state", {})
        with self.assertRaises(ValidationError):
            RealtimeEnvelope.create("browser.runtime", "invalid event", {})

    def test_commands_have_an_explicit_action_and_string_topic_list(self) -> None:
        self.assertEqual(
            RealtimeCommand(type="subscribe", topics=["browser.runtime"]).requested_topics,
            ["browser.runtime"],
        )
        for payload in (
            {"type": "unrecognized"},
            {"type": "subscribe", "topics": [123]},
            {"type": "subscribe", "topics": [{"topic": "browser.runtime"}]},
        ):
            with self.assertRaises(ValidationError):
                RealtimeCommand.model_validate(payload)
