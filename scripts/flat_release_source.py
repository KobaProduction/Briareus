"""Decode the checked-in release manifest into immutable source contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from coolify_snapshot import ApplicationIdentity, DevelopmentScope
from flat_release_plan import HeldApplication, ReleaseCandidate, ReleasePlan


@dataclass(frozen=True)
class ManifestRecord:
    fields: tuple[tuple[str, object], ...]

    @classmethod
    def parse(cls, value: object) -> ManifestRecord:
        if not isinstance(value, Mapping):
            raise ValueError("invalid reviewed release manifest object")
        pairs: list[tuple[str, object]] = []
        for key, item in cast(Mapping[object, object], value).items():
            if not isinstance(key, str):
                raise ValueError("invalid reviewed release manifest property")
            pairs.append((key, item))
        return cls(tuple(pairs))

    def value(self, name: str) -> object:
        for key, value in self.fields:
            if key == name:
                return value
        raise ValueError("missing reviewed release manifest property")

    def string(self, name: str) -> str:
        value = self.value(name)
        if not isinstance(value, str):
            raise ValueError("invalid reviewed release manifest string")
        return value

    def items(self, name: str) -> tuple[object, ...]:
        value = self.value(name)
        if not isinstance(value, list):
            raise ValueError("invalid reviewed release manifest list")
        return tuple(cast(list[object], value))

    def identity(self) -> ApplicationIdentity:
        return ApplicationIdentity(self.string("slug"), self.string("uuid"))


def _candidate(value: object) -> ReleaseCandidate:
    record = ManifestRecord.parse(value)
    watches: list[str] = []
    for watch in record.items("watch_paths"):
        if not isinstance(watch, str):
            raise ValueError("invalid reviewed release manifest watch pattern")
        watches.append(watch)
    return ReleaseCandidate(
        record.identity(),
        record.string("folder"),
        record.string("base_directory"),
        record.string("compose_location"),
        tuple(watches),
        record.string("toolchain"),
    )


def _held(value: object) -> HeldApplication:
    record = ManifestRecord.parse(value)
    # An absent action fails preservation rather than gaining a default grant.
    action = next((value for name, value in record.fields if name == "action"), "")
    if not isinstance(action, str):
        raise ValueError("invalid held application action")
    return HeldApplication(record.identity(), record.string("reason"), action)


def decode_release_plan(text: str) -> ReleasePlan:
    value: object = json.loads(text)
    record = ManifestRecord.parse(value)
    scope = ManifestRecord.parse(record.value("scope"))
    if frozenset(key for key, _ in scope.fields) != {"project", "environment", "repository"}:
        raise ValueError("invalid reviewed release scope")
    return ReleasePlan(
        DevelopmentScope(
            scope.string("project"), scope.string("environment"), scope.string("repository")
        ),
        tuple(_candidate(item) for item in record.items("candidates")),
        tuple(_held(item) for item in record.items("held")),
    )
