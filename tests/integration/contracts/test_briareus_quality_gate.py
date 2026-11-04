from __future__ import annotations

import json
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from scripts import quality_gate


class QualityGateContracts(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "service.py"
        self.source.write_text("def value() -> int:\n    return 1\n", encoding="utf-8")
        self.receipt = self.root / "quality-receipt.json"
        self.enterContext(patch.object(quality_gate, "ROOT", self.root))
        self.enterContext(patch.object(quality_gate, "git", return_value="test-index-metadata"))
        self.enterContext(patch.object(quality_gate, "receipt_path", return_value=self.receipt))
        self.enterContext(
            patch.object(
                quality_gate,
                "run",
                side_effect=AssertionError("External command was not mocked"),
            )
        )
        self.enterContext(
            patch.object(
                quality_gate.subprocess,
                "run",
                side_effect=AssertionError("External process was not mocked"),
            )
        )
        self.enterContext(
            patch.object(
                quality_gate.subprocess,
                "check_output",
                side_effect=AssertionError("Git command was not mocked"),
            )
        )

    def test_cognitive_rejects_real_nested_production_function(self) -> None:
        lines = ["def complex_function(value: bool) -> int:"]
        lines.extend("    " * depth + "if value:" for depth in range(1, 7))
        lines.extend(["    " * 7 + "return 1", "    return 0"])
        self.source.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"service.py:1:.*complexity 21 > 15"):
            quality_gate.cognitive([self.source])

    def test_cognitive_allows_simple_production_function(self) -> None:
        quality_gate.cognitive([self.source])

    def test_staged_rejects_unstaged_and_untracked_source(self) -> None:
        for unstaged, untracked in (("service.py", ""), ("", "new_service.py")):
            with self.subTest(unstaged=unstaged, untracked=untracked):
                responses = {
                    ("diff", "--name-only"): unstaged,
                    ("ls-files", "--others", "--exclude-standard"): untracked,
                }
                with (
                    patch.object(
                        quality_gate, "git", side_effect=lambda *args, table=responses: table[args]
                    ),
                    self.assertRaisesRegex(ValueError, "Stage all source changes"),
                ):
                    quality_gate.hook_paths("staged")

    def test_push_rejects_outgoing_commit_other_than_checked_out_head(self) -> None:
        responses = {
            ("diff", "--name-only"): "",
            ("ls-files", "--others", "--exclude-standard"): "",
            ("status", "--porcelain", "--untracked-files=no"): "",
            ("rev-parse", "HEAD"): "a" * 40,
        }
        outgoing = (
            f"refs/heads/new {'a' * 40} refs/heads/new {'0' * 40}\n"
            f"refs/heads/v1 {'b' * 40} refs/heads/v1 {'c' * 40}\n"
        )
        with (
            patch.object(quality_gate, "git", side_effect=lambda *args: responses[args]),
            patch.object(quality_gate.sys, "stdin", StringIO(outgoing)),
            self.assertRaisesRegex(ValueError, "Check out the outgoing commit"),
        ):
            quality_gate.hook_paths("push")

    def test_full_receipt_is_reused_only_for_identical_source(self) -> None:
        with (
            patch.object(quality_gate, "tracked_inputs", return_value=[self.source]),
            patch.object(quality_gate, "plan", return_value={"full": True}),
            patch.object(quality_gate, "static_checks") as static,
            patch.object(quality_gate, "full_tests") as tests,
            patch.object(quality_gate.sys, "argv", ["quality_gate", "--all", "--tests"]),
            patch("builtins.print"),
        ):
            quality_gate.main()
            first = json.loads(self.receipt.read_text(encoding="utf-8"))
            quality_gate.main()
            self.assertEqual(static.call_count, 1)
            self.assertEqual(tests.call_count, 1)
            self.source.write_text("def value() -> int:\n    return 2\n", encoding="utf-8")
            quality_gate.main()
            second = json.loads(self.receipt.read_text(encoding="utf-8"))
        self.assertNotEqual(first["tests"], second["tests"])
        self.assertEqual(second["static"], second["tests"])
        self.assertEqual(static.call_count, 2)
        self.assertEqual(tests.call_count, 2)

    def test_stale_full_test_receipt_cannot_authorize_staged_or_push_hook(self) -> None:
        with patch.object(quality_gate, "tracked_inputs", return_value=[self.source]):
            old = quality_gate.fingerprint()
            self.receipt.write_text(json.dumps({"static": old, "tests": old}), encoding="utf-8")
            self.source.write_text("def value() -> int:\n    return 2\n", encoding="utf-8")
            for mode in ("staged", "push"):
                with (
                    self.subTest(mode=mode),
                    patch.object(quality_gate, "hook_paths", return_value=["service.py"]),
                    patch.object(quality_gate, "plan", return_value={"full": True}),
                    patch.object(quality_gate, "static_checks") as static,
                    patch.object(quality_gate, "full_tests") as tests,
                    patch.object(quality_gate.sys, "argv", ["quality_gate", "--mode", mode]),
                    self.assertRaisesRegex(ValueError, "Run the final suite"),
                ):
                    quality_gate.main()
                static.assert_called_once()
                tests.assert_not_called()
            self.assertEqual(json.loads(self.receipt.read_text(encoding="utf-8"))["tests"], old)

    def test_source_change_during_validation_does_not_create_receipt(self) -> None:
        def change_source(_result: dict[str, object]) -> None:
            self.source.write_text("def value() -> int:\n    return 2\n", encoding="utf-8")

        with (
            patch.object(quality_gate, "tracked_inputs", return_value=[self.source]),
            patch.object(quality_gate, "plan", return_value={"full": True}),
            patch.object(quality_gate, "static_checks", side_effect=change_source),
            patch.object(quality_gate, "full_tests"),
            patch.object(quality_gate.sys, "argv", ["quality_gate", "--all", "--tests"]),
            self.assertRaisesRegex(ValueError, "Source changed during validation"),
        ):
            quality_gate.main()
        self.assertFalse(self.receipt.exists())

    def test_fingerprint_includes_index_metadata_even_when_source_bytes_match(self) -> None:
        with (
            patch.object(quality_gate, "tracked_inputs", return_value=[self.source]),
            patch.object(quality_gate, "git", return_value="100644 blob stage-zero"),
        ):
            first = quality_gate.fingerprint()
        with (
            patch.object(quality_gate, "tracked_inputs", return_value=[self.source]),
            patch.object(quality_gate, "git", return_value="100755 blob stage-zero"),
        ):
            second = quality_gate.fingerprint()
        self.assertNotEqual(first, second)
