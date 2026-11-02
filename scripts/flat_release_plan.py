"""Reviewed release identities and source topology policies, without deployment I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass

from coolify_snapshot import (
    ApplicationIdentity,
    DevelopmentScope,
    ExpectedApplication,
    SnapshotExpectation,
)


@dataclass(frozen=True)
class ReleaseCandidate:
    identity: ApplicationIdentity
    folder: str
    base_directory: str
    compose_location: str
    watch_paths: tuple[str, ...]
    toolchain: str

    @property
    def slug(self) -> str:
        return self.identity.slug

    def definition_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if (
            self.base_directory != "/" + self.folder
            or self.compose_location != "/docker-compose.coolify.yaml"
        ):
            errors.append(self.slug + ": incorrect Coolify Base or Compose path")
        if self.folder.startswith("hands/") and not {
            f"{self.folder}/**",
            "shared/hand_runtime/**",
            "services/external/**",
        }.issubset(self.watch_paths):
            errors.append(
                self.slug + ": Hand watches require own, shared runtime and External dependencies"
            )
        return tuple(errors)

    def watch_errors(self, actual: tuple[str, ...]) -> tuple[str, ...]:
        prefix = self.slug + ": "
        errors: list[str] = []
        if actual != self.watch_paths:
            errors.append(
                prefix + f"watch mismatch expected={list(self.watch_paths)}, actual={list(actual)}"
            )
        if not {f"{self.folder}/**", "services/external/**"}.issubset(actual):
            errors.append(prefix + "module and shared External directory watches required")
        if len(set(actual)) != len(actual):
            errors.append(prefix + "duplicate watch patterns")
        if set(actual) & {"**", "shared/**", "hands/**", "services/**", "deploy/**"}:
            errors.append(prefix + "unscoped watch path")
        return tuple(errors)

    def snapshot_expectation(self) -> ExpectedApplication:
        return ExpectedApplication(
            self.identity, self.base_directory, self.compose_location, self.watch_paths
        )

    def packaging_errors(
        self, *, portable: str, dockerfile: str, files: frozenset[str]
    ) -> tuple[str, ...]:
        prefix = self.slug + ": "
        errors: list[str] = []
        if not re.search(r"(?m)^\s+context:\s+\.\./\.\.\s*$", portable):
            errors.append(prefix + "build context is not the repository root")
        if f"dockerfile: {self.folder}/Dockerfile" not in portable:
            errors.append(prefix + "portable Compose points to another Dockerfile")
        if f"COPY {self.folder}/" not in dockerfile and self.toolchain != "upstream":
            errors.append(prefix + "Dockerfile lacks local source/lock COPY")
        required = {"python": {"pyproject.toml", "uv.lock"}, "bun": {"package.json", "bun.lock"}}
        if not required.get(self.toolchain, set()).issubset(files):
            label = "uv" if self.toolchain == "python" else "Bun"
            errors.append(prefix + "missing " + label + " project/lock")
        errors.extend(
            prefix + f"shared image dependency lacks Watch Paths: {package}"
            for package in re.findall(r"(?m)^COPY\s+(shared/[^\s/]+)(?:/|\s)", dockerfile)
            if f"{package}/**" not in self.watch_paths
        )
        if self.folder.startswith("hands/"):
            errors.extend(self._hand_image_errors(portable, dockerfile))
        return tuple(errors)

    def _hand_image_errors(self, portable: str, dockerfile: str) -> tuple[str, ...]:
        prefix = self.slug + ": "
        errors: list[str] = []
        if "read_only: true" not in portable or "cap_drop: [ALL]" not in portable:
            errors.append(prefix + "transitional Hand missing explicit unprivileged process bounds")
        if "COPY shared/hand_runtime/" not in dockerfile:
            errors.append(prefix + "selected shared module missing from Docker image")
        return tuple(errors)


@dataclass(frozen=True)
class HeldApplication:
    identity: ApplicationIdentity
    reason: str
    action: str

    @property
    def slug(self) -> str:
        return self.identity.slug

    def errors(self) -> tuple[str, ...]:
        if "preserve" not in self.action:
            return (self.slug + ": held application must preserve its existing configuration",)
        return ()


@dataclass(frozen=True)
class ReleasePlan:
    scope: DevelopmentScope
    candidates: tuple[ReleaseCandidate, ...]
    held: tuple[HeldApplication, ...]

    def scope_errors(self, allowlist: frozenset[ApplicationIdentity]) -> tuple[str, ...]:
        errors: list[str] = []
        if self.scope != DevelopmentScope(
            "3xshlpoghb9wcyhjgktlqzzp", "naibrku1omovvmw5o0bcnp5c", "KobaProduction/briareus"
        ):
            errors.append("scope does not match authorized Briareus Development")
        planned = tuple(item.identity for item in self.candidates) + tuple(
            item.identity for item in self.held
        )
        identifiers = tuple(identity.uuid for identity in planned)
        if len(identifiers) != 14 or len(set(identifiers)) != 14:
            errors.append("expected 14 different explicitly allowlisted applications")
        if set(planned) != allowlist:
            errors.append("manifest UUID/slug pairs differ from the approved Dev allowlist")
        return tuple(errors)

    def accepts_targets(self, targets: frozenset[str] | None) -> bool:
        return targets is None or (
            bool(targets) and targets.issubset(item.slug for item in self.candidates)
        )

    def snapshot_expectation(self) -> SnapshotExpectation:
        return SnapshotExpectation(
            self.scope,
            tuple(item.snapshot_expectation() for item in self.candidates),
            tuple(item.identity for item in self.held),
        )
