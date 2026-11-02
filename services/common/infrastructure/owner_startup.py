"""Owner-scoped SQL and telemetry resources; no foreign database lifecycle."""

from __future__ import annotations

from collections.abc import Callable

from common.application.owner_startup import OwnerSchemaStatus
from common.domain.owner_runtime import OwnerName
from common.owner_migrations import migrate_owner, owner_config, verify_owner
from common.owner_startup_diagnostics import Phase
from common.platform_db import OwnerDatabaseSettings, PlatformDatabase
from common.platform_telemetry import BriareusHttpTelemetry


class SqlOwnerSchemaLifecycle:
    def __init__(self, owner: OwnerName, settings: OwnerDatabaseSettings | None) -> None:
        self.owner = owner
        self.settings = settings
        self.database: PlatformDatabase | None = None
        self.telemetry: BriareusHttpTelemetry | None = None
        self._local: OwnerDatabaseSettings | None = None

    @property
    def available(self) -> bool:
        return self.database is not None

    def initialize(self, phase_change: Callable[[Phase], None]) -> None:
        local = self.settings or OwnerDatabaseSettings(owner=self.owner)
        if local.owner != self.owner:
            raise RuntimeError("owner runtime got foreign DB settings")
        self._local = local
        # Engine construction cannot create a PostgreSQL database, role or schema.
        phase_change("db_create")
        self.database = PlatformDatabase(local)
        self.telemetry = BriareusHttpTelemetry(
            "authorization" if self.owner == "access" else self.owner
        )
        self.telemetry.started()

    async def migrate(self, phase_change: Callable[[Phase], None]) -> None:
        database, local = self._resources()
        # One owner principal; never use an alternate DBA/migration DSN.
        owner_config(self.owner)
        await migrate_owner(database, local, phase_change=phase_change)

    def _resources(self) -> tuple[PlatformDatabase, OwnerDatabaseSettings]:
        if self.database is None or self._local is None:
            raise RuntimeError("owner schema lifecycle not initialized")
        return self.database, self._local

    async def verify(self, *, fresh_settings: bool = False) -> OwnerSchemaStatus:
        database, local = self._resources()
        if fresh_settings:
            local = self.settings or OwnerDatabaseSettings(owner=self.owner)
        observed = await verify_owner(database, local)
        return OwnerSchemaStatus(observed.revision, observed.tables)

    async def close(self) -> None:
        if self.telemetry is not None:
            self.telemetry.shutdown()
        if self.database is not None:
            await self.database.close()
