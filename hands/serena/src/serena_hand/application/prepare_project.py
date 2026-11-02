"""Prepare the private engine before activating an actual detected source project."""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from serena_hand.domain.languages import SourceLanguage, discover_languages


class ProjectPreparation(Protocol):
    def configure(self) -> None: ...

    def filenames(self, project: Path) -> Iterable[str]: ...

    def activate(self, project: Path, languages: tuple[SourceLanguage, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class PreparedProject:
    path: Path
    languages: tuple[SourceLanguage, ...]


@dataclass(frozen=True, slots=True)
class PrepareProject:
    backend: ProjectPreparation

    def execute(self, project: Path) -> PreparedProject:
        self.backend.configure()
        languages = discover_languages(self.backend.filenames(project))
        if languages:
            self.backend.activate(project, languages)
        return PreparedProject(project, languages)
