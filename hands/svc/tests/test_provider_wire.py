"""Provider IPC preserves JSON decoding without relaxing Python input strictness."""

import json
import time
import unittest
from uuid import UUID, uuid4

from mcp.types import CallToolRequestParams
from pydantic import ValidationError

from hand_runtime.provider_ipc import ProviderCommand, ProviderContext
from node_protocol.provider_context import ProjectAccount


def command(*, populated: bool = False) -> ProviderCommand:
    accounts: tuple[ProjectAccount, ...] = ()
    if populated:
        accounts = (
            ProjectAccount(
                id=uuid4(),
                alias="selected",
                provider="github",
                auth_type="github_token",
                base_url="https://api.github.com",
                external_id=None,
                ca_cert_pem=None,
                created_at="",
                updated_at="",
                credential="fixture-private-token",
            ),
        )
    return ProviderCommand(
        id=uuid4(),
        call=CallToolRequestParams(
            name="source_control_capabilities", arguments={"target": "github"}
        ),
        context=ProviderContext(accounts=accounts),
        expires_at=time.time() + 4,
    )


class ProviderWireTests(unittest.TestCase):
    def test_empty_and_populated_owner_context_roundtrip(self) -> None:
        for populated in (False, True):
            with self.subTest(populated=populated):
                original = command(populated=populated)
                restored = ProviderCommand.model_validate_json(
                    original.wire_json(exclude_unset=True)
                )
                self.assertEqual(restored, original)
                if populated:
                    self.assertIsInstance(restored.context.accounts[0].id, UUID)

    def test_python_lists_still_cannot_replace_strict_account_tuple(self) -> None:
        original = command()
        with self.assertRaises(ValidationError):
            ProviderCommand.model_validate(
                {
                    "id": original.id,
                    "call": original.call,
                    "context": {"accounts": []},
                    "expires_at": original.expires_at,
                }
            )

    def test_invalid_nested_account_and_unknown_context_remain_rejected(self) -> None:
        original = command(populated=True)
        wire = json.loads(original.wire_json())
        wire["context"]["accounts"][0]["id"] = "invalid"
        with self.assertRaises(ValidationError):
            ProviderCommand.model_validate_json(json.dumps(wire))
        wire = json.loads(original.wire_json())
        wire["context"]["unexpected"] = True
        with self.assertRaises(ValidationError):
            ProviderCommand.model_validate_json(json.dumps(wire))

    def test_nested_sdk_wire_is_still_rejected(self) -> None:
        wire = command().model_dump(mode="json")
        with self.assertRaises(ValidationError):
            ProviderCommand.model_validate_json(json.dumps(wire))
