"""An Analysis continuation retains its current start grant and revision."""

import unittest

from poll_authority_fixture import check_poll_authority


class AnalysisPollAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_only_and_changed_revision_cannot_resume_an_effect(self) -> None:
        await check_poll_authority(self, "reverse", None)
