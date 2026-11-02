"""Bounded source discovery does not invent a language for an empty workspace."""

from collections.abc import Iterable
from enum import Enum
from pathlib import PurePath


class SourceLanguage(Enum):
    CPP = "cpp"
    PYTHON = "python"
    TYPESCRIPT = "typescript"


SOURCE_LIMIT = 100_000
IGNORED_FOLDERS = frozenset({".git", ".venv", "node_modules", ".serena", "build", "dist"})


def language_for(filename: str) -> SourceLanguage | None:
    suffix = PurePath(filename).suffix.lower()
    if suffix in {".py", ".pyi"}:
        return SourceLanguage.PYTHON
    if suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
        return SourceLanguage.TYPESCRIPT
    if suffix in {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"}:
        return SourceLanguage.CPP
    return None


def discover_languages(filenames: Iterable[str]) -> tuple[SourceLanguage, ...]:
    selected: set[SourceLanguage] = set()
    for count, filename in enumerate(filenames, start=1):
        if count > SOURCE_LIMIT:
            raise ValueError("Explicit project subtree required for a larger source workspace")
        language = language_for(filename)
        if language is not None:
            selected.add(language)
    return tuple(sorted(selected, key=lambda language: language.value))
