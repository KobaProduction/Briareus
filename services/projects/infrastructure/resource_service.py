"""Team/Project reusable resources with current authorization and atomic mutations.

Resources are a separate bounded aggregate (in the Projects source ownership
lane), not children of the Team or Project business aggregate. No public
credential use transport is defined here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from common.audit_payloads import ResourceChangedAudit
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from common.platform_ids import PlatformProjectId, TeamId
from common.settings import ProcessSettings
from identity import UserRole
from projects._provider_registry import validate_provider
from projects._resource_domain import (
    EffectiveResource,
    OwnerScope,
    ResourceKind,
    ResourceOwner,
    ResourceScope,
    canonical_alias,
    canonical_variable_name,
)
from projects._resource_persistence import IntegrationRow, VariableRow
from projects._resource_repository import ResourceRepository
from projects.application.resolve_resource import ResolveProjectResource, ResolveResourceQuery
from projects.application.resource_ports import ProjectOwnerRevision, ResourceOwnerRevision
from projects.infrastructure.provider_metadata import StoredProviderSettings
from runtime_peer.domain.provider_settings import ProviderSettings

if TYPE_CHECKING:
    from authorization._platform_application import PlatformApplication
    from authorization._project_access import CallerPrincipal


class ResourceSettings(ProcessSettings):
    encryption_key: SecretStr = Field(validation_alias="CREDENTIAL_ENCRYPTION_KEY")


utcnow = partial(datetime.now, UTC)


def owner_of(row: IntegrationRow | VariableRow) -> ResourceOwner:
    if (row.owner_team_id is None) == (row.owner_project_id is None):
        raise AccessDenied("invalid persisted resource ownership")
    if row.owner_team_id is not None:
        return ResourceOwner(OwnerScope.TEAM, row.owner_team_id)
    if row.owner_project_id is None:
        raise AccessDenied("invalid persisted resource ownership")
    return ResourceOwner(OwnerScope.PROJECT, row.owner_project_id)


def view_of(
    row: IntegrationRow | VariableRow,
    *,
    inherited: bool,
) -> EffectiveResource:
    owner = owner_of(row)
    if isinstance(row, IntegrationRow):
        name = row.alias
        key = row.alias_key
        settings = row.provider_settings.record()
        display_name = settings.display_name[:128] if isinstance(settings.display_name, str) else ""
        return EffectiveResource(
            resource_id=row.id,
            kind=ResourceKind.INTEGRATION,
            owner=owner,
            name=name,
            key=key,
            version=row.version,
            inherited=inherited,
            is_secret=True,
            provider=row.provider,
            auth_type=row.auth_type,
            display_name=display_name,
            provider_settings=settings,
            credential_configured=bool(row.encrypted_credential),
            connection_status="unverified",
            updated_at=row.updated_at,
        )
    return EffectiveResource(
        resource_id=row.id,
        kind=ResourceKind.VARIABLE,
        owner=owner,
        name=row.name_key,
        key=row.name_key,
        version=row.version,
        inherited=inherited,
        is_secret=row.is_secret,
        value=None if row.is_secret else row.plain_value,
        updated_at=row.updated_at,
    )


class MutableIntegration(NamedTuple):
    row: IntegrationRow
    owner: ResourceOwner
    owner_row: ResourceOwnerRevision


class MutableVariable(NamedTuple):
    row: VariableRow
    owner: ResourceOwner
    owner_row: ResourceOwnerRevision


class ResourceService:
    """All current permissions are checked on the authoritative new database.

    Management Team rights are deliberately MEMBER-based, unlike membership
    administration/ownership transfer, which remain Team OWNER-only.
    """

    def __init__(self, application: PlatformApplication, *, encryption_key: str) -> None:
        # PlatformApplication is injected to avoid Project-domain -> Auth import.
        self.application = application
        self.repository = ResourceRepository()
        self._cipher = Fernet(encryption_key.encode())

    def seal(self, value: str) -> str:
        if not 1 <= len(value.encode()) <= 131072:
            raise InvalidInput("secret value length is invalid")
        return self._cipher.encrypt(value.encode()).decode()

    def _open_for_trusted_adapter(self, ciphertext: str) -> SecretStr:
        """MUST NOT be used by API serializers/logs or called before access check."""
        return SecretStr(self._cipher.decrypt(ciphertext.encode()).decode())

    async def _check_team(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        team_id: TeamId,
        *,
        lock: bool,
    ) -> ResourceOwnerRevision:
        actor = await self.application.current_user(tx, caller, lock=lock)
        team = await self.application.teams.get(tx, team_id, lock=lock)
        if team is None or (
            actor.role is not UserRole.SUPERUSER
            and not await self.application.teams.active_member(tx, team_id, caller.user_id)
        ):
            raise AccessDenied("Team resource access denied")
        return team

    async def _check_project(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        *,
        lock: bool,
    ) -> ProjectOwnerRevision:
        # All mutating owner paths acquire User before Project before Team.
        # Inverting this order could deadlock a credential lease against a
        # concurrent ownership transfer or Team membership revoke.
        await self.application.current_user(tx, caller, lock=lock)
        project = await self.application.projects.get(tx, project_id, lock=lock)
        if project is None:
            raise AccessDenied("Project resource access denied")
        if project.owner_team_id is not None:
            # Membership revoke and Team resource mutations lock Team row.
            await self._check_team(tx, caller, TeamId(project.owner_team_id), lock=lock)
        await self.application.project_allowed(tx, caller, project_id)
        return project

    async def _check_owner(
        self, tx: AsyncSession, caller: CallerPrincipal, owner: ResourceOwner, *, lock: bool
    ) -> ResourceOwnerRevision:
        if owner.scope is OwnerScope.TEAM:
            return await self._check_team(tx, caller, TeamId(owner.owner_id), lock=lock)
        if owner.scope is OwnerScope.PROJECT:
            return await self._check_project(
                tx, caller, PlatformProjectId(owner.owner_id), lock=lock
            )
        raise InvalidInput("resource owner scope is invalid")

    def _record_change(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        owner: ResourceOwner,
        owner_row: ResourceOwnerRevision,
        resource_id: UUID,
        *,
        kind: ResourceKind,
        action: str,
        version: int,
    ) -> None:
        # The owner row is locked, so revision increments cannot be lost.
        owner_row.resource_revision += 1
        context_project = owner.project_id
        self.application._audit(
            tx,
            actor=caller.user_id,
            project=context_project,
            action=f"resource.{kind.value}.{action}",
            target=resource_id,
            event=ResourceChangedAudit(
                owner_scope=owner.scope.value,
                owner_id=owner.owner_id,
                resource_id=resource_id,
                resource_version=version,
                owner_resource_revision=owner_row.resource_revision,
                invalidate_effective_project_cache=True,
            ),
        )

    async def _authorized_project_owners(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        scope: ResourceScope,
        *,
        lock: bool = False,
    ) -> tuple[ResourceOwner, ...]:
        row = await self._check_project(tx, caller, project_id, lock=lock)
        if scope is ResourceScope.TEAM:
            if row.owner_team_id is None:
                raise AccessDenied("personal Project has no Team resources")
            return (ResourceOwner(OwnerScope.TEAM, row.owner_team_id),)
        if scope is ResourceScope.PROJECT:
            return (ResourceOwner(OwnerScope.PROJECT, project_id),)
        if scope is ResourceScope.ALL:
            owners: tuple[ResourceOwner, ...] = (
                (ResourceOwner(OwnerScope.TEAM, row.owner_team_id),)
                if row.owner_team_id is not None
                else ()
            )
            return (*owners, ResourceOwner(OwnerScope.PROJECT, project_id))
        raise InvalidInput("scope must be all, team or project")

    async def list_for_project(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        kind: ResourceKind,
        *,
        scope: ResourceScope = ResourceScope.ALL,
    ) -> list[EffectiveResource]:
        if not isinstance(kind, ResourceKind):
            raise InvalidInput("unknown resource kind")
        owners = await self._authorized_project_owners(tx, caller, project_id, scope)
        found: list[EffectiveResource] = []
        for owner in owners:
            rows = (
                await self.repository.integrations_for(tx, owner)
                if kind is ResourceKind.INTEGRATION
                else await self.repository.variables_for(tx, owner)
            )
            found.extend(view_of(row, inherited=owner.scope is OwnerScope.TEAM) for row in rows)
        return sorted(
            found,
            key=lambda value: (
                value.key,
                value.owner.scope.value,
                str(value.resource_id),
            ),
        )

    async def list_for_team(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        team_id: TeamId,
        kind: ResourceKind,
    ) -> list[EffectiveResource]:
        if not isinstance(kind, ResourceKind):
            raise InvalidInput("unknown resource kind")
        await self._check_team(tx, caller, team_id, lock=False)
        owner = ResourceOwner(OwnerScope.TEAM, team_id)
        rows = (
            await self.repository.integrations_for(tx, owner)
            if kind is ResourceKind.INTEGRATION
            else await self.repository.variables_for(tx, owner)
        )
        return [view_of(row, inherited=False) for row in rows]

    async def resolve_for_project(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        kind: ResourceKind,
        *,
        resource_id: UUID | None = None,
        name: str | None = None,
        scope: ResourceScope = ResourceScope.ALL,
    ) -> EffectiveResource:
        return await ResolveProjectResource(
            _CurrentProjectResources(self, tx, caller, project_id)
        ).execute(ResolveResourceQuery(kind, resource_id, name, scope))

    async def create_integration(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        *,
        owner: ResourceOwner,
        alias: str,
        provider: str,
        auth_type: str,
        provider_settings: ProviderSettings,
        credential: str,
    ) -> EffectiveResource:
        owner_row = await self._check_owner(tx, caller, owner, lock=True)
        alias, key = canonical_alias(alias)
        canonical_provider = provider.strip().casefold()
        canonical_auth_type = auth_type.strip().casefold()
        validated = validate_provider(canonical_provider, canonical_auth_type, provider_settings)
        if any(row.alias_key == key for row in await self.repository.integrations_for(tx, owner)):
            raise Conflict("integration alias already exists within selected owner")
        row = IntegrationRow(
            id=uuid4(),
            alias=alias,
            alias_key=key,
            provider=canonical_provider,
            auth_type=canonical_auth_type,
            provider_settings=StoredProviderSettings.from_record(validated),
            encrypted_credential=self.seal(credential),
            version=1,
            owner_team_id=owner.team_id,
            owner_project_id=owner.project_id,
        )
        tx.add(row)
        await tx.flush()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=ResourceKind.INTEGRATION,
            action="created",
            version=1,
        )
        return view_of(row, inherited=False)

    async def create_variable(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        *,
        owner: ResourceOwner,
        name: str,
        value: str,
        is_secret: bool,
    ) -> EffectiveResource:
        owner_row = await self._check_owner(tx, caller, owner, lock=True)
        key = canonical_variable_name(name)
        if any(row.name_key == key for row in await self.repository.variables_for(tx, owner)):
            raise Conflict("variable name already exists within selected owner")
        if len(value.encode()) > 131072:
            raise InvalidInput("variable value is too large")
        row = VariableRow(
            id=uuid4(),
            name_key=key,
            is_secret=is_secret,
            encrypted_value=self.seal(value) if is_secret else None,
            plain_value=None if is_secret else value,
            version=1,
            owner_team_id=owner.team_id,
            owner_project_id=owner.project_id,
        )
        tx.add(row)
        await tx.flush()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=ResourceKind.VARIABLE,
            action="created",
            version=1,
        )
        return view_of(row, inherited=False)

    async def _mutable_integration(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
    ) -> MutableIntegration:
        # Owner is immutable: peek only for owner ID, lock owner and re-fetch.
        probe = await self.repository.integration(tx, resource_id)
        if probe is None:
            raise AccessDenied("resource unavailable")
        owner = owner_of(probe)
        owner_row = await self._check_owner(tx, caller, owner, lock=True)
        row = await self.repository.integration(tx, resource_id, lock=True)
        if row is None or owner_of(row) != owner:
            raise AccessDenied("resource unavailable")
        return MutableIntegration(row, owner, owner_row)

    async def _mutable_variable(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
    ) -> MutableVariable:
        probe = await self.repository.variable(tx, resource_id)
        if probe is None:
            raise AccessDenied("resource unavailable")
        owner = owner_of(probe)
        owner_row = await self._check_owner(tx, caller, owner, lock=True)
        row = await self.repository.variable(tx, resource_id, lock=True)
        if row is None or owner_of(row) != owner:
            raise AccessDenied("resource unavailable")
        return MutableVariable(row, owner, owner_row)

    async def update_integration(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
        *,
        expected_version: int,
        alias: str | None = None,
        provider_settings: ProviderSettings | None = None,
    ) -> EffectiveResource:
        row, owner, owner_row = await self._mutable_integration(tx, caller, resource_id)
        if row.version != expected_version:
            raise Conflict("integration version conflict")
        if alias is not None:
            label, key = canonical_alias(alias)
            if key != row.alias_key and any(
                item.alias_key == key for item in await self.repository.integrations_for(tx, owner)
            ):
                raise Conflict("integration alias already exists within selected owner")
            row.alias, row.alias_key = label, key
        if provider_settings is not None:
            validated = validate_provider(row.provider, row.auth_type, provider_settings)
            row.provider_settings = StoredProviderSettings.from_record(validated)
        if alias is None and provider_settings is None:
            raise InvalidInput("at least one mutable field is required")
        row.version += 1
        row.updated_at = utcnow()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=ResourceKind.INTEGRATION,
            action="updated",
            version=row.version,
        )
        return view_of(row, inherited=False)

    async def rotate_integration(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
        *,
        expected_version: int,
        credential: str,
    ) -> EffectiveResource:
        row, owner, owner_row = await self._mutable_integration(tx, caller, resource_id)
        if row.version != expected_version:
            raise Conflict("integration version conflict")
        row.encrypted_credential = self.seal(credential)
        row.version += 1
        row.updated_at = utcnow()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=ResourceKind.INTEGRATION,
            action="rotated",
            version=row.version,
        )
        return view_of(row, inherited=False)

    async def update_variable(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
        *,
        expected_version: int,
        name: str,
    ) -> EffectiveResource:
        row, owner, owner_row = await self._mutable_variable(tx, caller, resource_id)
        if row.version != expected_version:
            raise Conflict("variable version conflict")
        key = canonical_variable_name(name)
        if key != row.name_key and any(
            item.name_key == key for item in await self.repository.variables_for(tx, owner)
        ):
            raise Conflict("variable name already exists within selected owner")
        row.name_key = key
        row.version += 1
        row.updated_at = utcnow()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=ResourceKind.VARIABLE,
            action="updated",
            version=row.version,
        )
        return view_of(row, inherited=False)

    async def rotate_variable(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
        *,
        expected_version: int,
        value: str,
        is_secret: bool,
    ) -> EffectiveResource:
        row, owner, owner_row = await self._mutable_variable(tx, caller, resource_id)
        if row.version != expected_version:
            raise Conflict("variable version conflict")
        if len(value.encode()) > 131072:
            raise InvalidInput("variable value is too large")
        row.is_secret = is_secret
        row.encrypted_value = self.seal(value) if is_secret else None
        row.plain_value = None if is_secret else value
        row.version += 1
        row.updated_at = utcnow()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=ResourceKind.VARIABLE,
            action="rotated",
            version=row.version,
        )
        return view_of(row, inherited=False)

    async def revoke(
        self,
        tx: AsyncSession,
        caller: CallerPrincipal,
        resource_id: UUID,
        kind: ResourceKind,
        *,
        expected_version: int,
    ) -> EffectiveResource:
        if not isinstance(kind, ResourceKind):
            raise InvalidInput("unknown resource kind")
        row: IntegrationRow | VariableRow
        if kind is ResourceKind.INTEGRATION:
            row, owner, owner_row = await self._mutable_integration(tx, caller, resource_id)
        else:
            row, owner, owner_row = await self._mutable_variable(tx, caller, resource_id)
        if row.version != expected_version:
            raise Conflict("resource version conflict")
        row.deleted_at = utcnow()
        row.version += 1
        row.updated_at = utcnow()
        self._record_change(
            tx,
            caller,
            owner,
            owner_row,
            row.id,
            kind=kind,
            action="revoked",
            version=row.version,
        )
        return view_of(row, inherited=False)


@dataclass(frozen=True)
class _CurrentProjectResources:
    service: ResourceService
    tx: AsyncSession
    caller: CallerPrincipal
    project_id: PlatformProjectId

    async def load(self, kind: ResourceKind, scope: ResourceScope) -> tuple[EffectiveResource, ...]:
        return tuple(
            await self.service.list_for_project(
                self.tx, self.caller, self.project_id, kind, scope=scope
            )
        )
