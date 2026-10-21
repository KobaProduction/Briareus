"""Run in the Serena upstream venv with empty disposable /project-data."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from serena_hand.runtime import prepare_project,server_parameters


class EmptyStartupTests(unittest.TestCase):
    def test_empty_workspace_does_not_invent_a_language_or_project(self):
        root=Path('/project-data')
        self.assertEqual(list(root.iterdir()),[])
        with patch.dict(os.environ,{'SERENA_HOME':'/home/hand/.serena'}),patch(
            'serena.config.serena_config.ProjectConfig.autogenerate',side_effect=AssertionError('No source language exists')):
            self.assertEqual(prepare_project('.'),root)
        self.assertEqual(list(root.iterdir()),[])

    def test_real_upstream_start_is_unactivated_and_usage_reporting_disabled(self):
        parameters=server_parameters(Path('/project-data'))
        self.assertNotIn('--project',parameters.args)
        self.assertIn('--language-backend',parameters.args)
        self.assertEqual(parameters.env['SERENA_USAGE_REPORTING'],'false')
        self.assertEqual(parameters.command,'/opt/serena/.venv/bin/serena')
