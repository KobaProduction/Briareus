#!/usr/bin/env python3
"""Bounded, read-only source preflight for the approved Briareus Dev rebaseline.

Owner-approved disposable SERVICE data is not a permission to reset Rauthy,
PGDATA, Valkey, Files roots, or another Coolify environment. This command
prints the immutable targeted source mapping and outstanding real-world
evidence; it NEVER executes SQL, updates a runtime or reports reset approval.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple, TypedDict

from pydantic import BaseModel, ConfigDict, StrictStr

from coolify_snapshot import ApplicationIdentity, DevelopmentScope
from owner_schema_git import GitOwnerSources


class ScopeWire(TypedDict):
    project: str
    environment: str
    repository: str


class InvalidCandidateRef(TypedDict):
    state: Literal["INVALID_CANDIDATE_REF"]
    release_authorized: Literal[False]


class UnverifiedPreflight(TypedDict):
    state: Literal["SOURCE_REBASELINE_UNVERIFIED"]
    release_authorized: Literal[False]


class OwnerReport(TypedDict):
    owner: str
    application_slug: str
    application_uuid: str
    logical_database: str
    expected_new_revision: str


class CompletedPreflight(TypedDict):
    state: Literal["SOURCE_REBASELINE_CONTRADICTED", "SOURCE_CONTRACT_OK_LIVE_RESET_BLOCKED"]
    target_backend_commit: str
    scope: ScopeWire
    affected_only: list[OwnerReport]
    always_protected_databases: list[str]
    protected_filesystem: list[str]
    runtime_preconditions_unverified: list[str]
    source_findings: list[str]
    source_contract_pass: bool
    release_authorized: Literal[False]
    sql_executed: Literal[False]
    coolify_mutated: Literal[False]


type PreflightInspection = InvalidCandidateRef | CompletedPreflight
type PreflightResult = PreflightInspection | UnverifiedPreflight


class OwnerTarget(NamedTuple):
    service: str
    database: str
    expected_head: str
    expected_uuid: str


@dataclass(frozen=True)
class ObservedApplication:
    slug: str
    identity: ApplicationIdentity | None
    uuid_label: str

    def matches(self, expected_uuid: str) -> bool:
        return self.identity is not None and self.identity.uuid == expected_uuid


class DatabaseOwnerSource(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    database: StrictStr


class DatabaseInventorySource(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    initial: tuple[DatabaseOwnerSource, ...] | None = None
    protected_provider_databases: tuple[StrictStr, ...] | None = None


class ManifestScopeSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    project: StrictStr
    environment: StrictStr
    repository: StrictStr

    def scope(self) -> DevelopmentScope:
        return DevelopmentScope(self.project, self.environment, self.repository)


class ApplicationIdentitySource(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    slug: StrictStr | None = None
    uuid: StrictStr | None = None


class ManifestInspectionSource(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    scope: ManifestScopeSource | None = None
    candidates: tuple[ApplicationIdentitySource, ...] | None = None


@dataclass(frozen=True)
class ManifestSource:
    scope: DevelopmentScope | None
    applications: dict[str, ObservedApplication]
    candidates_available: bool


@dataclass(frozen=True)
class DatabaseSource:
    protected_providers: tuple[str, ...] | None
    initial_available: bool
    databases: frozenset[str]
    database_labels_valid: bool


class SourceConfiguration(NamedTuple):
    manifest: ManifestSource
    external: DatabaseSource


@dataclass(frozen=True)
class ReviewedOwnerRevisions:
    owner: str
    revisions: tuple[str, ...]


@dataclass(frozen=True)
class ReviewedRevisions:
    owners: tuple[ReviewedOwnerRevisions, ...]

    def __bool__(self) -> bool:
        return bool(self.owners)

    def get(self, owner: str) -> tuple[str, ...] | None:
        return next((entry.revisions for entry in self.owners if entry.owner == owner), None)


@dataclass(frozen=True)
class OwnerSourceCheck:
    report: OwnerReport
    findings: tuple[str, ...]


ROOT = Path(__file__).resolve().parents[1]
_SCOPE: ScopeWire = {
    "project": "3xshlpoghb9wcyhjgktlqzzp",
    "environment": "naibrku1omovvmw5o0bcnp5c",
    "repository": "KobaProduction/briareus",
}
_TARGETS = {
    "access": (
        "authorization",
        "briareus_access",
        "access_20261015_0001",
        "95podguiawtnf2tvlemvk3ef",
    ),
    "platform": (
        "platform",
        "briareus_platform",
        "platform_20261015_0001",
        "uvr5zfb9729ptfyfuxo3htmc",
    ),
    "resources": (
        "resources",
        "briareus_resources",
        "resources_20261015_0001",
        "6vdxwespr1ufxeohy6xpa7wg",
    ),
}
_PROTECTED = frozenset(
    {
        "briareus_rauthy",
        "briareus_identity",
        "briareus_dev",
        "briareus_files",
        "briareus_runtime",
        "briareus_reverse",
    }
)
_PINNED_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)


@dataclass(frozen=True)
class GitBlobSource:
    revision: str
    relative_path: str

    def __post_init__(self) -> None:
        if not _PINNED_SHA.fullmatch(self.revision):
            raise ValueError("source blob requires exact committed SHA")
        parts = self.relative_path.split("/")
        if (
            not self.relative_path.startswith("services/")
            or any(part in {"", ".", ".."} for part in parts)
            or chr(0) in self.relative_path
        ):
            raise ValueError("source blob requires a repository service path")


def _git_blob(ref: str, path: str, *, repo: Path = ROOT) -> str | None:
    source = GitBlobSource(ref, path)
    return GitOwnerSources(repo).read_blob(source.revision, source.relative_path, limit=140000)


def _manifest_source(source: str) -> ManifestSource:
    manifest = ManifestInspectionSource.model_validate_json(source)
    applications: dict[str, ObservedApplication] = {}
    for application in manifest.candidates or ():
        if application.slug is None:
            continue
        identity = (
            ApplicationIdentity(application.slug, application.uuid)
            if application.uuid is not None
            else None
        )
        applications[application.slug] = ObservedApplication(
            application.slug, identity, str(application.uuid)
        )
    return ManifestSource(
        manifest.scope.scope() if manifest.scope is not None else None,
        applications,
        manifest.candidates is not None,
    )


def _database_source(source: str) -> DatabaseSource:
    inventory = DatabaseInventorySource.model_validate_json(source)
    return DatabaseSource(
        inventory.protected_provider_databases,
        inventory.initial is not None,
        frozenset(entry.database for entry in inventory.initial or ()),
        True,
    )


def _source_configuration(repo: Path) -> SourceConfiguration:
    manifest = (repo / "docs/operations/flat-batch-cutover.json").read_text()
    external = (repo / "services/external/config/owner-databases.json").read_text()
    return SourceConfiguration(_manifest_source(manifest), _database_source(external))


def _configuration_findings(configuration: SourceConfiguration) -> list[str]:
    manifest, external = configuration
    errors: list[str] = []
    expected = DevelopmentScope(_SCOPE["project"], _SCOPE["environment"], _SCOPE["repository"])
    if manifest.scope != expected:
        errors.append("Development project/environment/repository scope differs")
    if not manifest.candidates_available:
        errors.append("approved Dev Application list missing")
    if external.protected_providers != ("briareus_rauthy",):
        errors.append("Rauthy provider protected set must remain exact")
    if not external.initial_available:
        errors.append("PostgreSQL logical DB owner inventory unavailable")
    if not external.database_labels_valid or external.databases != {
        value[1] for value in _TARGETS.values()
    } | {"briareus_rauthy"}:
        errors.append("External DB owner inventory differs from exactly approved four names")
    return errors


def _reviewed_owner(owner: str, value: ast.expr) -> ReviewedOwnerRevisions:
    if not isinstance(value, ast.Tuple) or not value.elts:
        raise ValueError("invalid reviewed owner revision map")
    revisions: list[str] = []
    for revision in value.elts:
        if not isinstance(revision, ast.Constant) or not isinstance(revision.value, str):
            raise ValueError("invalid reviewed owner revision map")
        revisions.append(revision.value)
    return ReviewedOwnerRevisions(owner, tuple(revisions))


def _revision_entries(expression: ast.Dict) -> tuple[ReviewedOwnerRevisions, ...]:
    entries: dict[str, ast.expr] = {}
    for key, value in zip(expression.keys, expression.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise ValueError("invalid reviewed owner revision map")
        entries[key.value] = value
    return tuple(_reviewed_owner(owner, value) for owner, value in entries.items())


def _revisions(source: str) -> ReviewedRevisions:
    for item in ast.parse(source).body:
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and item.target.id == "_REVIEWED_VERSIONS"
        ):
            if not isinstance(item.value, ast.Dict):
                raise ValueError("reviewed owner revision map absent")
            return ReviewedRevisions(_revision_entries(item.value))
    raise ValueError("reviewed owner revision map absent")


def _baseline_revision(source: str) -> str | None:
    for item in ast.parse(source).body:
        if (
            isinstance(item, ast.Assign)
            and len(item.targets) == 1
            and isinstance(item.targets[0], ast.Name)
            and item.targets[0].id == "revision"
        ):
            return (
                item.value.value
                if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str)
                else None
            )
    return None


def _inspect_owner(
    ref: str,
    owner: str,
    target: OwnerTarget,
    application: ObservedApplication | None,
    revisions: ReviewedRevisions,
    *,
    repo: Path,
) -> OwnerSourceCheck:
    service, database, expected_head, expected_uuid = target
    errors: list[str] = []
    if application is None or not application.matches(expected_uuid):
        errors.append(service + ": not an approved exact Development Application UUID")
    compose = _git_blob(ref, f"services/{service}/docker-compose.yaml", repo=repo)
    dockerfile = _git_blob(ref, f"services/{service}/Dockerfile", repo=repo)
    ignored = _git_blob(ref, f"services/{service}/Dockerfile.dockerignore", repo=repo)
    baseline_path = f"services/{service}/migrations/versions/0001_{owner}_baseline.py"
    migration = _git_blob(ref, baseline_path, repo=repo)
    expected = revisions.get(owner)
    if expected != (expected_head,):
        errors.append(service + ": expected greenfield one-revision epoch unavailable")
    if (
        not isinstance(compose, str)
        or len(re.findall(rf'(?m)^\s+POSTGRES_DB:\s*["\']{re.escape(database)}["\']\s*$', compose))
        != 1
    ):
        errors.append(service + ": owner logical database differs or is not uniquely pinned")
    if not isinstance(migration, str) or _baseline_revision(migration) != expected_head:
        errors.append(service + ": greenfield baseline revision not pinned")
    if not isinstance(dockerfile, str) or (
        f"COPY {baseline_path} "
        f"/app/src/common/alembic_owners/{owner}/versions/0001_{owner}_baseline.py"
        not in dockerfile
    ):
        errors.append(service + ": current migration baseline is absent from Docker image")
    if not isinstance(ignored, str) or (
        "**" in ignored.splitlines() and f"!{baseline_path}" not in ignored.splitlines()
    ):
        errors.append(service + ": current migration excluded from Docker build context")
    return OwnerSourceCheck(
        OwnerReport(
            owner=owner,
            application_slug=service,
            application_uuid=application.uuid_label if application is not None else "",
            logical_database=database,
            expected_new_revision=expected_head,
        ),
        tuple(errors),
    )


def inspect(ref: str, *, repo: Path = ROOT) -> PreflightInspection:
    """Static source mapping only: no remote discovery or secret access."""
    if not _PINNED_SHA.fullmatch(ref):
        return InvalidCandidateRef(state="INVALID_CANDIDATE_REF", release_authorized=False)
    configuration = _source_configuration(repo)
    errors = _configuration_findings(configuration)
    owner_code = _git_blob(ref, "services/common/owner_migrations.py", repo=repo)
    try:
        revision_registry = (
            _revisions(owner_code) if owner_code is not None else ReviewedRevisions(())
        )
    except (ValueError, SyntaxError, TypeError, MemoryError):
        revision_registry = ReviewedRevisions(())
    if not revision_registry:
        errors.append("exact candidate reviewed owner migration registry unavailable")
    reports: list[OwnerReport] = []
    for owner, raw_target in _TARGETS.items():
        target = OwnerTarget(*raw_target)
        checked = _inspect_owner(
            ref,
            owner,
            target,
            configuration.manifest.applications.get(target.service),
            revision_registry,
            repo=repo,
        )
        errors.extend(checked.findings)
        reports.append(checked.report)
    if any(x["logical_database"] in _PROTECTED for x in reports):
        errors.append("protected provider/legacy/root database included in reset targets")
    return CompletedPreflight(
        state="SOURCE_REBASELINE_CONTRADICTED"
        if errors
        else "SOURCE_CONTRACT_OK_LIVE_RESET_BLOCKED",
        target_backend_commit=ref,
        scope=_SCOPE,
        affected_only=reports,
        always_protected_databases=sorted(_PROTECTED),
        protected_filesystem=[
            "existing Project Files root bytes and mounts",
            "owner-authorized Files root mappings until independently reconciled",
        ],
        runtime_preconditions_unverified=[
            "current scoped owner inspector: database, role, Alembic version and row counts",
            "actual owner rows, sessions, approvals and Project/Files root mapping inventory",
            "recoverable owner-only DB snapshots and verified restore; provider protected",
            "approved exact Coolify app stop/restart capability plus dependency-deny plan",
            "actual Rauthy and shared PGDATA/Valkey/Files-storage protection after any reset",
            "candidate Backend image SHA, Compose parity and post-start schema verification",
        ],
        source_findings=errors,
        source_contract_pass=not errors,
        release_authorized=False,
        sql_executed=False,
        coolify_mutated=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-sha", required=True, help="exact committed backend git SHA")
    opts = parser.parse_args()
    report: PreflightResult
    try:
        report = inspect(opts.backend_sha)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        report = UnverifiedPreflight(state="SOURCE_REBASELINE_UNVERIFIED", release_authorized=False)
    print(json.dumps(report, indent=2))
    return 2 if report.get("source_contract_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
