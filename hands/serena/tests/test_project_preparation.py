"""Language activation is bounded and independent of filesystem/upstream effects."""

import tempfile
import unittest
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from serena_hand.application.prepare_project import PrepareProject
from serena_hand.domain.languages import SOURCE_LIMIT, SourceLanguage, discover_languages
from serena_hand.infrastructure.project_preparation import UpstreamProjectPreparation


@dataclass
class PreparationFixture:
    source: tuple[str, ...]
    events: list[str] = field(default_factory=list)
    activated: tuple[SourceLanguage, ...] = ()

    def configure(self) -> None:
        self.events.append("configured")

    def filenames(self, _project: Path) -> Iterable[str]:
        self.events.append("scanned")
        return self.source

    def activate(self, _project: Path, languages: tuple[SourceLanguage, ...]) -> None:
        self.events.append("activated")
        self.activated = languages


class ProjectPreparationTests(unittest.TestCase):
    def test_empty_and_unknown_sources_never_invent_activation(self) -> None:
        for source in ((), ("README.md", "photo.png")):
            with self.subTest(source=source):
                backend = PreparationFixture(source)
                result = PrepareProject(backend).execute(Path("/project-data"))
                self.assertEqual(result.languages, ())
                self.assertEqual(backend.events, ["configured", "scanned"])

    def test_detected_languages_are_unique_sorted_and_activated_after_configuration(self) -> None:
        backend = PreparationFixture(("a.PY", "b.pyi", "page.tsx", "lib.h", "x.cxx", "ui.mjs"))
        result = PrepareProject(backend).execute(Path("/project-data/source"))
        self.assertEqual(result.path, Path("/project-data/source"))
        self.assertEqual(
            result.languages,
            (
                SourceLanguage.CPP,
                SourceLanguage.PYTHON,
                SourceLanguage.TYPESCRIPT,
            ),
        )
        self.assertEqual(backend.activated, result.languages)
        self.assertEqual(backend.events, ["configured", "scanned", "activated"])

    def test_scan_limit_counts_unknown_files_and_stops_before_activation(self) -> None:
        self.assertEqual(discover_languages("readme" for _ in range(SOURCE_LIMIT)), ())
        with self.assertRaisesRegex(ValueError, "Explicit project subtree"):
            discover_languages("readme" for _ in range(SOURCE_LIMIT + 1))

    def test_configuration_failure_prevents_scanning(self) -> None:
        class FailedConfiguration(PreparationFixture):
            def configure(self) -> None:
                raise ValueError("private configuration unavailable")

        backend = FailedConfiguration(("source.py",))
        with self.assertRaisesRegex(ValueError, "private configuration"):
            PrepareProject(backend).execute(Path("/project-data"))
        self.assertEqual(backend.events, [])

    def test_filesystem_scan_excludes_generated_and_dependency_subtrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in (".git", ".venv", "node_modules", ".serena", "build", "dist"):
                (root / folder).mkdir()
                (root / folder / "ignored.py").touch()
            (root / "source").mkdir()
            (root / "source" / "app.ts").touch()
            backend = object.__new__(UpstreamProjectPreparation)
            self.assertEqual(tuple(backend.filenames(root)), ("app.ts",))

    def test_invalid_private_home_cannot_be_used(self) -> None:
        with self.assertRaisesRegex(ValueError, "Private placement"):
            UpstreamProjectPreparation(Path("/project-data/shared-home"))
