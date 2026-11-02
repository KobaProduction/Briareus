"""Static owner-history invariants; never imports or executes migration source."""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MigrationRevision:
    filename: str
    revision: str
    predecessor: str | None


@dataclass(frozen=True)
class MigrationHistory:
    revisions: tuple[MigrationRevision, ...]

    def __post_init__(self) -> None:
        identifiers = [entry.revision for entry in self.revisions]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("invalid source Alembic revision")

    def get(self, revision: str) -> MigrationRevision | None:
        return next((entry for entry in self.revisions if entry.revision == revision), None)

    def image_errors(
        self,
        folder: str,
        owner: str,
        chain: tuple[str, ...],
        dockerfile: str,
        ignore_lines: Sequence[str],
    ) -> list[str]:
        errors: list[str] = []
        if {entry.revision for entry in self.revisions} != set(chain):
            errors.append(folder + ": shipped migration files differ from reviewed graph")
        for index, revision in enumerate(chain):
            entry = self.get(revision)
            if entry is None:
                continue
            if entry.predecessor != (chain[index - 1] if index else None):
                errors.append(folder + ": owner history has unexpected ancestor")
            errors.extend(entry_image_errors(entry, folder, owner, dockerfile, ignore_lines))
        return errors


@dataclass
class _MigrationFields:
    revision: str | None = None
    predecessor: str | None = None
    predecessor_valid: bool = True

    def assign(self, field: str, value: object) -> None:
        # Invalid literal types remain invalid until all assignments are read.
        # A later assignment to the same field still replaces the earlier one.
        if field == "revision":
            self.revision = value if isinstance(value, str) else None
        else:
            self.predecessor = value if isinstance(value, str) else None
            self.predecessor_valid = value is None or isinstance(value, str)

    def checked(self, filename: str) -> MigrationRevision:
        if self.revision is None or not self.predecessor_valid:
            raise ValueError("invalid source Alembic revision")
        return MigrationRevision(filename, self.revision, self.predecessor)


def reviewed_chain(source: str, owner: str) -> tuple[str, ...]:
    for node in ast.parse(source).body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "_REVIEWED_VERSIONS" or node.value is None:
            continue
        return _owner_chain(ast.literal_eval(node.value), owner)
    raise ValueError("invalid reviewed owner graph")


def _owner_chain(mapping: object, owner: str) -> tuple[str, ...]:
    chain: object = mapping.get(owner) if isinstance(mapping, dict) else None
    if not isinstance(chain, tuple) or not chain:
        raise ValueError("invalid reviewed owner graph")
    revisions: list[str] = []
    for item in chain:
        if not isinstance(item, str):
            raise ValueError("invalid reviewed owner graph")
        revisions.append(item)
    return tuple(revisions)


def migration_revision(filename: str, source: str) -> MigrationRevision:
    fields = _MigrationFields()
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
            fields.assign(target.id, ast.literal_eval(node.value))
    return fields.checked(filename)


def entry_image_errors(
    entry: MigrationRevision,
    folder: str,
    owner: str,
    dockerfile: str,
    ignore_lines: Sequence[str],
) -> list[str]:
    source = f"{folder}/migrations/versions/{entry.filename}"
    destination = f"/app/src/common/alembic_owners/{owner}/versions/{entry.filename}"
    copy = rf"(?m)^COPY\s+{re.escape(source)}\s+{re.escape(destination)}\s*$"
    errors: list[str] = []
    if len(re.findall(copy, dockerfile)) != 1:
        errors.append(folder + ": Dockerfile missing migration " + entry.filename)
    if "**" in ignore_lines and f"!{source}" not in ignore_lines:
        errors.append(folder + ": Docker build context excludes migration " + entry.filename)
    return errors
