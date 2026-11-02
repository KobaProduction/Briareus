"""Source and public-provider evidence; never credential or provisioning authority."""

from __future__ import annotations

import re
from dataclasses import dataclass

SECURE_FLAGS = (
    "OPEN_USER_REG",
    "USER_REG_OPEN_REDIRECT",
    "ENABLE_DYN_CLIENT_REG",
    "ENABLE_EPHEMERAL_CLIENTS",
)
PRIVATE_JWK_FIELDS = frozenset({"d", "p", "q", "dp", "dq", "qi", "oth", "k"})


@dataclass(frozen=True, slots=True)
class SourceCheck:
    name: str
    passed: bool


@dataclass(frozen=True, slots=True)
class EnrollmentFlag:
    name: str
    disabled: bool


@dataclass(frozen=True, slots=True)
class ComposeEvidence:
    filename: str
    checks: tuple[SourceCheck, ...]
    security_fields: tuple[EnrollmentFlag, ...]


@dataclass(frozen=True, slots=True)
class DatabaseInventory:
    active: frozenset[str]
    protected: frozenset[str]
    legacy: frozenset[str]


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    portable: str
    coolify: str
    entrypoint: str
    provider_health: str
    postgres_image: str
    ignored_inputs: tuple[str, ...]
    bootstrap: str
    preflight: str
    inventory: DatabaseInventory


@dataclass(frozen=True, slots=True)
class SourceReport:
    compose: tuple[ComposeEvidence, ...]
    checks: tuple[SourceCheck, ...]

    @property
    def source_pass(self) -> bool:
        return all(check.passed for check in self.checks) and all(
            check.passed for compose in self.compose for check in compose.checks
        )


def _compose(filename: str, source: str) -> ComposeEvidence:
    flags = tuple(
        EnrollmentFlag(
            flag, re.findall(r"^\s+" + flag + r':\s*"([^"]+)"\s*$', source, re.M) == ["false"]
        )
        for flag in SECURE_FLAGS
    )
    return ComposeEvidence(
        filename,
        (
            SourceCheck(filename + ".enrollment_disabled", all(flag.disabled for flag in flags)),
            SourceCheck(
                filename + ".private_vendor_network",
                "name: briareus-net" in source and "ports:" not in source,
            ),
            SourceCheck(
                filename + ".canonical_bootstrap_db",
                'POSTGRES_DB: "postgres"' in source and "briareus_dev" not in source,
            ),
        ),
        flags,
    )


def _postgres_checks(source: SourceSnapshot) -> tuple[SourceCheck, ...]:
    image, entrypoint, health = source.postgres_image, source.entrypoint, source.provider_health
    copy_inputs = (
        "postgres-entrypoint.sh",
        "provider-db-health.sh",
        "owner-bootstrap.psql",
        "owner-readiness.psql",
    )
    return (
        SourceCheck(
            "postgres_image_sources_in_build_context",
            all(
                f"!services/external/{filename}" in source.ignored_inputs
                and f"COPY services/external/{filename} " in image
                for filename in copy_inputs
            ),
        ),
        SourceCheck(
            "rauthy_waits_for_provider_db_prerequisite",
            all(
                fragment in text
                for text, fragment in (
                    (
                        source.portable,
                        'test: ["CMD", "/usr/local/bin/briareus-provider-db-health"]',
                    ),
                    (source.portable, "condition: service_healthy"),
                    (entrypoint, "provider_ready_file=/run/briareus-rauthy-db-ready"),
                    (entrypoint, "pg_get_userbyid(datdba) = current_user"),
                    (entrypoint, 'if [ "$provider_owned" = t ]; then'),
                    (image, "COPY services/external/provider-db-health.sh"),
                )
            ),
        ),
        SourceCheck(
            "provider_db_health_checks_current_catalog",
            all(
                fragment in health
                for fragment in (
                    "test -f /run/briareus-rauthy-db-ready",
                    "pg_isready -h 127.0.0.1 -p 5432",
                    "PGPASSWORD",
                    "-w -v ON_ERROR_STOP=1",
                    "count(*) = 1 AND bool_and(pg_get_userbyid(datdba) = current_user)",
                    "FROM pg_database WHERE datname = 'briareus_rauthy'",
                    '[ "$provider_owned" = t ]',
                )
            ),
        ),
        SourceCheck(
            "owner_db_reconciliation_not_provider_health_gate",
            "owner_ready_file=/run/briareus-owner-databases-ready" in entrypoint
            and "briareus-owner-databases-ready" not in health
            and 'if [ "$owners_reconciled" = true ]; then' in entrypoint,
        ),
    )


def _portable_checks(source: SourceSnapshot) -> tuple[SourceCheck, ...]:
    portable = source.portable
    valkey = portable.partition("  briareus-valkey:")[2].partition("  briareus-rauthy:")[0]
    return (
        SourceCheck(
            "valkey_auth_reservations_not_evicted",
            re.findall(r"maxmemory-policy ([a-z-]+)\\n", valkey) == ["noeviction"],
        ),
        SourceCheck(
            "compose_dns_preserved",
            all(
                alias in portable
                for alias in (
                    'aliases: ["briareus-postgres"]',
                    'aliases: ["briareus-valkey"]',
                    'aliases: ["briareus-rauthy"]',
                )
            ),
        ),
        SourceCheck(
            "compose_vendor_volumes_declared",
            all(
                volume in portable
                for volume in (
                    "postgres-data:/var/lib/postgresql",
                    "valkey-data:/data",
                    "rauthy-data:/app/data",
                )
            ),
        ),
    )


def _bootstrap_checks(source: SourceSnapshot) -> tuple[SourceCheck, ...]:
    bootstrap = source.bootstrap
    create = bootstrap.partition("SELECT format(")[2].partition("\\gexec")[0]
    return (
        SourceCheck(
            "active_database_inventory",
            source.inventory.active
            == {
                "briareus_access",
                "briareus_platform",
                "briareus_resources",
                "briareus_rauthy",
            },
        ),
        SourceCheck("provider_db_protected", source.inventory.protected == {"briareus_rauthy"}),
        SourceCheck(
            "fresh_bootstrap_provider_created_first",
            "ORDER BY (wanted.dbname = 'briareus_rauthy') DESC, wanted.dbname" in create,
        ),
        SourceCheck(
            "legacy_db_not_provisioned",
            source.inventory.legacy
            == {
                "briareus_identity",
                "briareus_dev",
            }
            and "briareus_identity" not in create
            and "briareus_dev" not in create
            and bool(create),
        ),
        SourceCheck("missing_rauthy_db_fails_closed", _provider_guard(bootstrap)),
        SourceCheck(
            "non_destructive_postgres_bootstrap",
            "count(*) = 4" in bootstrap
            and "briareus_rauthy" in bootstrap
            and "DROP DATABASE" not in bootstrap.upper()
            and "TRUNCATE" not in bootstrap.upper()
            and "CREATE DATABASE" in bootstrap,
        ),
    )


def _provider_guard(bootstrap: str) -> bool:
    guard = bootstrap.partition("\\gset")[0]
    names = (
        "briareus_access",
        "briareus_platform",
        "briareus_resources",
        "briareus_files",
        "briareus_runtime",
        "briareus_reverse",
        "briareus_ingest",
        "briareus_identity",
        "briareus_dev",
    )
    return (
        "EXISTS (SELECT 1 FROM pg_database WHERE datname = 'briareus_rauthy')" in guard
        and "OR NOT EXISTS (" in guard
        and all("'" + name + "'" in guard for name in names)
        and "AS provider_bootstrap_safe" in guard
        and "\\if :provider_bootstrap_safe" in bootstrap
        and "\\else" in bootstrap
        and "protected Rauthy database missing on existing cluster" in bootstrap
        and bootstrap.index("\\gset") < bootstrap.index("\\gexec")
    )


def _preflight(source: str) -> SourceCheck:
    statements = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("--", "\\"))
    )
    blocked = re.search(
        r"\b(DROP|ALTER|CREATE|TRUNCATE|INSERT|UPDATE|DELETE|GRANT|"
        r"REVOKE|COPY|EXECUTE|VACUUM|CALL|DO)\b",
        statements,
        re.IGNORECASE,
    )
    names = (
        "briareus_rauthy",
        "briareus_access",
        "briareus_platform",
        "briareus_resources",
        "briareus_files",
        "briareus_runtime",
        "briareus_reverse",
        "briareus_ingest",
        "briareus_identity",
        "briareus_dev",
    )
    return SourceCheck(
        "preflight_is_catalog_select_only",
        (
            re.match(r"^SELECT\s+", statements.lstrip(), re.IGNORECASE) is not None
            and statements.count(";") == 1
            and blocked is None
            and "FROM (VALUES" in statements
            and "pg_database" in statements
            and "pg_stat_database" in statements
            and all(statements.count("'" + name + "'") == 1 for name in names)
        ),
    )


def inspect_source(source: SourceSnapshot) -> SourceReport:
    return SourceReport(
        (
            _compose("docker-compose.yaml", source.portable),
            _compose("docker-compose.coolify.yaml", source.coolify),
        ),
        (
            *_postgres_checks(source),
            *_portable_checks(source),
            *_bootstrap_checks(source),
            _preflight(source.preflight),
        ),
    )


@dataclass(frozen=True, slots=True)
class ProviderEndpoints:
    issuer: str
    authorization: str
    token: str
    jwks: str


@dataclass(frozen=True, slots=True)
class DiscoveryEvidence:
    issuer: bool
    authorize: bool
    token: bool
    jwks: bool
    authorization_code: bool
    pkce_s256: bool

    @property
    def passed(self) -> bool:
        return all(
            (
                self.issuer,
                self.authorize,
                self.token,
                self.jwks,
                self.authorization_code,
                self.pkce_s256,
            )
        )


@dataclass(frozen=True, slots=True)
class PublicKeyEvidence:
    status: int
    count: int | None = None
    no_private_fields: bool = False
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RouteStatus:
    name: str
    path: str
    status: int


@dataclass(frozen=True, slots=True)
class PublicReport:
    discovery_status: int
    discovery: DiscoveryEvidence | None = None
    keys: PublicKeyEvidence | None = None
    routes: tuple[RouteStatus, ...] = ()

    def __post_init__(self) -> None:
        if self.discovery_status != 200:
            if self.discovery is not None or self.keys is not None or self.routes:
                raise ValueError("Failed discovery cannot attest downstream provider evidence")
            return
        expected = {
            "admin",
            "self_user_by_id",
            "admin_attributes",
            "admin_clients",
            "registration_users",
            "registration_root",
        }
        if (
            self.discovery is None
            or self.keys is None
            or len(self.routes) != len(expected)
            or {route.name for route in self.routes} != expected
        ):
            raise ValueError("Complete provider evidence required")

    @property
    def public_oidc_pass(self) -> bool:
        return (
            self.discovery is not None
            and self.discovery.passed
            and self.keys is not None
            and self.keys.status == 200
            and self.keys.no_private_fields
        )

    @property
    def admin_route_privacy_accepted(self) -> bool:
        return all(
            route.status == 404
            for route in self.routes
            if route.name in {"admin", "admin_attributes", "admin_clients"}
        )

    @property
    def self_user_status(self) -> int:
        return next(route.status for route in self.routes if route.name == "self_user_by_id")

    @property
    def public_pass(self) -> bool:
        return (
            self.public_oidc_pass
            and self.admin_route_privacy_accepted
            and self.self_user_status in {401, 403, 404}
        )


@dataclass(frozen=True, slots=True)
class PublicFailure:
    error_type: str
