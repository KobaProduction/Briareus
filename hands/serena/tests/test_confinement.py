import tempfile
import unittest
from pathlib import Path
from serena_hand.confinement import project_root, confine_arguments


class ConfinementTests(unittest.TestCase):
    def test_relative_project_uses_only_own_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "source").mkdir()
            self.assertEqual(project_root("source", workspace), workspace / "source")
            for invalid in ("../outside", "/etc", "C:/Users", "a\\b", "a\0b"):
                with self.assertRaises(ValueError):
                    project_root(invalid, workspace)

    def test_source_tools_reject_outside_paths_and_projects(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            self.assertEqual(confine_arguments("find_symbol", {"relative_path": "source.py"}, project),
                             {"relative_path": "source.py"})
            for tool, arguments in [("activate_project", {"project": "/etc"}),
                                    ("find_symbol", {"relative_path": "../outside.py"}),
                                    ("execute_shell_command", {"command": "pwd", "cwd": "/etc"}),
                                    ("open_dashboard", {})]:
                with self.assertRaises(ValueError):
                    confine_arguments(tool, arguments, project)
            self.assertEqual(confine_arguments("execute_shell_command", {"command": "pwd", "cwd": "."}, project),
                             {"command": "pwd", "cwd": "."})

    def test_symlink_cannot_activate_another_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "workspace"
            outside = base / "outside"
            workspace.mkdir()
            outside.mkdir()
            try:
                (workspace / "escape").symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Platform cannot create symlink")
            with self.assertRaises(ValueError):
                project_root("escape", workspace)
            with self.assertRaises(ValueError):
                confine_arguments("get_symbols_overview", {"relative_path": "escape/file.py"}, workspace)
