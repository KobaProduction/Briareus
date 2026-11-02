"""A Serena continuation retains current original-tool and start rights."""

import unittest

from poll_authority_fixture import check_poll_authority


class SerenaPollAuthorityTests(unittest.IsolatedAsyncioTestCase):
    async def test_poll_only_and_changed_revision_cannot_resume_an_effect(self) -> None:
        await check_poll_authority(self, "serena", "rename_symbol")
