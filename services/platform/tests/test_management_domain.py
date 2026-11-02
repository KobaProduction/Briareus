"""Rename concurrency and ownership are independent of the SQL adapter."""

import unittest
from uuid import uuid4

from projects.domain.management import ManagedProject, ManagedTeam, ManagementError, name


class ManagementDomainTests(unittest.TestCase):
    def test_team_owner_cannot_be_removed_or_revision_changed(self) -> None:
        owner = uuid4()
        team = ManagedTeam(uuid4(), "Team", owner, 4)
        with self.assertRaises(ManagementError) as raised:
            team.change_member(owner, False)
        self.assertEqual(raised.exception.code, "TEAM_OWNER_REQUIRED")
        self.assertEqual(team.resource_revision, 4)
        team.change_member(uuid4(), True)
        self.assertEqual(team.resource_revision, 5)

    def test_rename_preserves_optimistic_expected_name_check(self) -> None:
        team = ManagedTeam(uuid4(), "Current", uuid4(), 0)
        with self.assertRaises(ManagementError) as raised:
            team.rename("Previous", "Next")
        self.assertEqual(raised.exception.code, "NAME_CHANGED")
        self.assertEqual(team.name, "Current")
        team.rename("Current", " Next ")
        self.assertEqual(team.name, "Next")

    def test_project_requires_one_owner(self) -> None:
        with self.assertRaises(ManagementError):
            ManagedProject(uuid4(), "Project", None, None)
        with self.assertRaises(ManagementError):
            ManagedProject(uuid4(), "Project", uuid4(), uuid4())

    def test_names_keep_existing_bounds_and_control_character_rejection(self) -> None:
        for value in (None, " ", "x" * 256, "line\nfeed", "delete\x7f"):
            with self.subTest(value=value), self.assertRaises(ManagementError):
                name(value)
