from __future__ import annotations

import unittest
from dataclasses import dataclass

from bridge.application.access_session import AdmitSessionTool, SessionToolAttempt
from common.access_contracts import OAuthContext, ValidationResult


@dataclass(frozen=True, slots=True)
class ValidationAttempt:
    actor: OAuthContext
    surface_id: int
    session_uid: str
    tool: str
    full_access: bool
    account: str


class ValidationStub:
    def __init__(self) -> None:
        self.attempts: list[ValidationAttempt] = []
        self.decision = ValidationResult(allowed=False, code="session_required")

    async def validate(
        self,
        *,
        context: OAuthContext,
        surface_id: int,
        session_uid: str,
        tool_name: str,
        requires_full_access: bool,
        account_id: str,
    ) -> ValidationResult:
        self.attempts.append(
            ValidationAttempt(
                context,
                surface_id,
                session_uid,
                tool_name,
                requires_full_access,
                account_id,
            )
        )
        return self.decision


class SessionAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.port = ValidationStub()
        self.admission = AdmitSessionTool(self.port)
        self.actor = OAuthContext(user_id="user", client_id="client", oauth_session_id="oauth")

    async def test_unknown_effect_requires_full_access_and_current_authority(self) -> None:
        decision = await self.admission.execute(
            self.actor,
            SessionToolAttempt(
                "github",
                1,
                "modify",
                "session",
                "account",
                False,
            ),
        )
        self.assertIs(decision, self.port.decision)
        self.assertFalse(decision.allowed)
        self.assertEqual(
            self.port.attempts,
            [
                ValidationAttempt(
                    self.actor,
                    1,
                    "session",
                    "modify",
                    True,
                    "account",
                )
            ],
        )

    async def test_safe_discovery_still_checks_authority_once_per_call(self) -> None:
        attempt = SessionToolAttempt("github", 1, "github_accounts", "", "", False)
        await self.admission.execute(self.actor, attempt)
        await self.admission.execute(self.actor, attempt)
        self.assertEqual(len(self.port.attempts), 2)
        self.assertTrue(all(not item.full_access for item in self.port.attempts))

    async def test_discovery_allowlist_is_bound_to_its_surface(self) -> None:
        await self.admission.execute(
            self.actor,
            SessionToolAttempt(
                "files",
                2,
                "github_accounts",
                "session",
                "",
                False,
            ),
        )
        self.assertTrue(self.port.attempts[0].full_access)


if __name__ == "__main__":
    unittest.main()
