"""Preserve concrete runtime reference and workspace-root constructor contracts."""

from pathlib import Path


class _WorkspaceBinding[WorkspaceT]:
    def __init__(self, workspace: WorkspaceT) -> None:
        self._workspace = workspace


class _EffectsBinding[EffectsT]:
    def __init__(self, effects: EffectsT) -> None:
        self.effects = effects


class _PrivateRootBinding:
    def __init__(self, root: Path) -> None:
        self._root = root
