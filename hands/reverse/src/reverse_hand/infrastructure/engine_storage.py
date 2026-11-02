"""Prepare isolated engine subdirectories before native runtimes start."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EngineStorage:
    ghidra: Path
    radare2: Path


def prepare_storage(root: Path) -> EngineStorage:
    for name in ("ghidra", "radare2"):
        directory = root / name
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Separate private engine storage required")
        os.chmod(directory, 0o700)
    return EngineStorage(root / "ghidra", root / "radare2")
