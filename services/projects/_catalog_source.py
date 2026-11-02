"""Resource Catalog-owned one-use leases, no Identity/Project SQL joins.

Credentials remain inside Catalog. Only a verified private service peer may
exchange a source-signed lease for a SecretStr. No browser/Gateway mounts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from cryptography.fernet import InvalidToken
from pydantic import SecretStr
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from common.infrastructure.audit_records import ResourceAccessAudit
from common.infrastructure.owner_event_records import (
    IntegrationCredentialRedeemed,
    VariableCredentialRedeemed,
)
from common.owner_contracts import (
    OwnerCommandDTO,
    SignedOwnerProofs,
    VerifiedOwnerOperation,
    VerifiedOwnerServicePeer,
    require_online_owner_decision,
    require_signed_payload,
)
from common.owner_transactions import OwnerCommandOutcome
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects._catalog_ledger import OwnerAuditRow, OwnerOutboxRow
from projects._resource_domain import canonical_variable_name
from projects._resource_persistence import CredentialLeaseRow, IntegrationRow, VariableRow
from projects.application.owner_receipts import (
    CatalogChangeIntegration,
    CatalogChangeVariable,
    CatalogCreateVariable,
    CatalogReserveIntegration,
    CatalogReserveVariable,
)
from projects.catalog.application._command_payloads import (
    ChangeCatalogIntegrationPayload,
    ChangeCatalogVariablePayload,
    CreateCatalogVariablePayload,
    ListCatalogMetadataPayload,
    RedeemCatalogLeasePayload,
    ReserveIntegrationPayload,
    ReserveVariablePayload,
)
from projects.catalog.infrastructure.creation import _CatalogCreation
from projects.infrastructure.catalog_variables import write_variable_content


@dataclass(frozen=True, slots=True)
class CatalogLeaseHandle:
    lease_id: UUID
    owner_scope: str
    owner_id: UUID
    resource_version: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class CatalogResourceSummary:
    """Provenance metadata ONLY; never provider payload or plaintext secrets."""

    resource_id: UUID
    resource_type: Literal["integration", "variable"]
    alias_key: str
    owner_scope: Literal["team", "project"]
    owner_id: UUID
    version: int


def _metadata_filters(
    row_type: type[IntegrationRow] | type[VariableRow],
    request: OwnerCommandDTO,
    scope: Literal["all", "team", "project"],
) -> list[ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = []
    if scope in {"all", "project"}:
        filters.append(row_type.owner_project_id == request.project_id)
    if scope in {"all", "team"} and request.expected_team_id is not None:
        filters.append(row_type.owner_team_id == request.expected_team_id)
    return filters


def _require_effective_selector(
    request: OwnerCommandDTO,
    kind: Literal["integrations", "variables"],
    scope: Literal["all", "team", "project"],
    alias_key: str | None,
    limit: int,
) -> None:
    if (
        request.target_owner != "resources"
        or request.operation != f"catalog.{kind}.list"
        or not 1 <= limit <= 100
        or (alias_key is not None and not 1 <= len(alias_key) <= 128)
        or (scope == "team" and request.expected_team_id is None)
    ):
        raise AccessDenied("Catalog resource scope/query not source-authorized")


def _resource_summary(
    row: IntegrationRow | VariableRow,
    kind: Literal["integrations", "variables"],
) -> CatalogResourceSummary:
    owning_team = row.owner_team_id
    owner_scope: Literal["team", "project"] = "team" if owning_team is not None else "project"
    owner_id = owning_team if owning_team is not None else row.owner_project_id
    if owner_id is None:
        raise AccessDenied("Catalog resource violates XOR owner provenance")
    return CatalogResourceSummary(
        resource_id=row.id,
        resource_type="integration" if kind == "integrations" else "variable",
        alias_key=row.alias_key if isinstance(row, IntegrationRow) else row.name_key,
        owner_scope=owner_scope,
        owner_id=owner_id,
        version=row.version,
    )


def _require_integration_revision(
    request: OwnerCommandDTO,
    owner_scope: str,
    owner_id: UUID,
) -> None:
    if (
        owner_scope == "team"
        and (
            request.expected_team_id != owner_id
            or request.expected_team_revision is None
            or request.expected_team_resource_revision is None
        )
    ) or (
        owner_scope == "project"
        and (
            request.expected_team_id is not None
            or request.expected_team_revision is not None
            or request.expected_team_resource_revision is not None
        )
    ):
        raise AccessDenied("Catalog ownership revision proof incomplete or inconsistent")


def _require_peer_binding(
    peer: VerifiedOwnerServicePeer,
    service_id: UUID,
    instance_uuid: UUID,
    audience: str,
    failure: str,
) -> None:
    if (
        peer.service_id != service_id
        or peer.instance_uuid != instance_uuid
        or peer.audience != audience
        or peer.expires_at <= datetime.now(UTC)
    ):
        raise AccessDenied(failure)


class CatalogSourceService(_CatalogCreation):
    async def reserve_integration(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        integration_id: UUID,
        expected_resource_version: int,
        owner_scope: str,
        owner_id: UUID,
        service_id: UUID,
        service_instance_uuid: UUID,
        service_audience: str,
        expires_in_seconds: int = 60,
    ) -> OwnerCommandOutcome[CatalogReserveIntegration]:
        if (
            decision.request.operation != "credential.reserve"
            or integration_id.version != 4
            or owner_id.version != 4
            or service_id.version != 4
            or service_instance_uuid.version != 4
            or owner_scope not in {"team", "project"}
            or expected_resource_version < 1
            or not service_audience.startswith("briareus:")
            or not 1 <= expires_in_seconds <= 60
        ):
            raise InvalidInput("invalid Catalog resource lease parameters")
        _require_integration_revision(decision.request, owner_scope, owner_id)
        require_signed_payload(
            decision.request,
            asdict(
                ReserveIntegrationPayload(
                    integration_id=str(integration_id),
                    expected_resource_version=expected_resource_version,
                    owner_scope=owner_scope,
                    owner_id=str(owner_id),
                    service_id=str(service_id),
                    service_instance_uuid=str(service_instance_uuid),
                    service_audience=service_audience,
                    expires_in_seconds=expires_in_seconds,
                )
            ),
        )

        async def mutate(tx: AsyncSession) -> CatalogReserveIntegration:
            row = await tx.scalar(
                select(IntegrationRow).where(IntegrationRow.id == integration_id).with_for_update()
            )
            if (
                row is None
                or row.deleted_at is not None
                or row.version != expected_resource_version
            ):
                raise AccessDenied("Catalog resource not available at attested revision")
            if (
                owner_scope == "team"
                and (row.owner_team_id != owner_id or row.owner_project_id is not None)
            ) or (
                owner_scope == "project"
                and (
                    row.owner_project_id != decision.request.project_id
                    or owner_id != row.owner_project_id
                    or row.owner_team_id is not None
                )
            ):
                raise AccessDenied("Catalog source ownership/provenance mismatch")
            expires = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
            lease = CredentialLeaseRow(
                id=uuid4(),
                project_id=decision.request.project_id,
                user_id=decision.request.caller_user_id,
                session_uuid=decision.request.session_uuid,
                resource_id=integration_id,
                kind="integration",
                owner_scope=owner_scope,
                owner_id=owner_id,
                resource_version=row.version,
                service_id=service_id,
                service_instance_uuid=service_instance_uuid,
                operation_uuid=decision.request.operation_uuid,
                service_audience=service_audience,
                correlation_id=decision.request.operation_uuid,
                project_version=decision.request.expected_control_revision,
                project_resource_revision=decision.request.expected_control_resource_revision,
                team_version=decision.request.expected_team_revision,
                team_resource_revision=decision.request.expected_team_resource_revision,
                session_version=decision.request.expected_access_revision,
                expires_at=expires,
                redeemed_at=None,
            )
            tx.add(lease)
            return CatalogReserveIntegration(
                lease_id=str(lease.id),
                owner_scope=owner_scope,
                owner_id=str(owner_id),
                resource_version=row.version,
                expires_at=expires.isoformat(),
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutate,
            event="catalog.lease_reserved",
            target=str(integration_id),
            response_model=CatalogReserveIntegration,
        )

    async def redeem_integration(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        lease_id: UUID,
        service_id: UUID,
        instance_uuid: UUID,
        audience: str,
        peer_evidence: object,
    ) -> SecretStr:
        """Single-use and never replayable; caller must be a trusted native peer.

        HTTP C1-B2/C2 transport remains deliberately unavailable. Returning
        a SecretStr here is only a private in-process adapter boundary.
        """
        if request.operation != "credential.redeem" or any(
            value.version != 4 for value in (lease_id, service_id, instance_uuid)
        ):
            raise AccessDenied("credential lease signed operation invalid")
        # Service identity comes from the independently injected native peer
        # verifier, never a JSON body, service UUID, HTTP header or bearer.
        try:
            peer = self.peer_verifier.verify_peer(peer_evidence)
            _require_peer_binding(
                peer,
                service_id,
                instance_uuid,
                audience,
                "Catalog service peer did not match lease recipient",
            )
        except Exception:
            raise AccessDenied("independent service peer authentication required") from None
        require_signed_payload(
            request,
            asdict(
                RedeemCatalogLeasePayload(
                    lease_id=str(lease_id),
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    audience=audience,
                )
            ),
        )
        first = self.source.require_current(request, proofs)
        fresh = await require_online_owner_decision(self.source, self.current_owners, request)
        if not first.same_epochs(fresh):
            raise AccessDenied("credential owner revocation fence changed")
        if request.target_owner != "resources":
            raise AccessDenied("wrong Catalog recipient")
        async with self.db.transaction() as tx:
            lease = await tx.get(CredentialLeaseRow, lease_id, with_for_update=True)
            if (
                lease is None
                or lease.project_id != request.project_id
                or lease.session_uuid != request.session_uuid
                or lease.user_id != request.caller_user_id
                or lease.service_id != service_id
                or lease.service_instance_uuid != instance_uuid
                or lease.service_audience != audience
                or lease.redeemed_at is not None
                or lease.expires_at <= datetime.now(UTC)
                or lease.session_version != request.expected_access_revision
                or lease.project_version != request.expected_control_revision
                or lease.project_resource_revision != request.expected_control_resource_revision
                or lease.team_version != request.expected_team_revision
                or lease.team_resource_revision != request.expected_team_resource_revision
            ):
                raise AccessDenied("credential lease consumed, expired or no longer authorized")
            resource = await tx.get(IntegrationRow, lease.resource_id, with_for_update=True)
            if (
                resource is None
                or resource.deleted_at is not None
                or resource.version != lease.resource_version
                or (lease.owner_scope == "team" and resource.owner_team_id != lease.owner_id)
                or (lease.owner_scope == "project" and resource.owner_project_id != lease.owner_id)
            ):
                raise Conflict("Catalog resource revision changed; lease fenced")
            try:
                cleartext = self.cipher.decrypt(resource.encrypted_credential.encode()).decode()
            except (InvalidToken, UnicodeDecodeError):
                raise AccessDenied("Catalog encrypted credential unavailable") from None
            again = await require_online_owner_decision(self.source, self.current_owners, request)
            if not fresh.same_epochs(again):
                raise AccessDenied("Catalog proof revoked before one-use consume")
            lease.redeemed_at = datetime.now(UTC)
            tx.add(
                OwnerAuditRow(
                    operation_uuid=request.operation_uuid,
                    actor_user_id=request.caller_user_id,
                    project_id=request.project_id,
                    action="catalog.credential_redeemed",
                    object_id=str(lease.id),
                    owner_revision=str(request.expected_control_resource_revision),
                    details=ResourceAccessAudit(
                        resource_id=lease.resource_id, service_id=service_id
                    ),
                )
            )
            tx.add(
                OwnerOutboxRow(
                    operation_uuid=request.operation_uuid,
                    event_name="catalog.credential_redeemed",
                    owner_revision=str(request.expected_control_resource_revision),
                    event_payload=IntegrationCredentialRedeemed(
                        project_id=request.project_id,
                        lease_id=lease.id,
                        service_id=service_id,
                        operation_uuid=request.operation_uuid,
                    ),
                )
            )
            # Secret material is intentionally NOT copied into outbox, command
            # results, audit, frontend data, logs or a durable lease row.
            return SecretStr(cleartext)

    async def list_effective_metadata(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        kind: Literal["integrations", "variables"],
        scope: Literal["all", "team", "project"] = "all",
        alias_key: str | None = None,
        limit: int = 100,
    ) -> tuple[CatalogResourceSummary, ...]:
        """Both origins coexist; ambiguous alias never implicitly overrides.

        A Team-owned Project inherits ONLY its verified owner's Team resources.
        A personal Project must not receive any Team integrations/variables.
        No credentials/variables values/provider_settings are returned.
        """
        _require_effective_selector(request, kind, scope, alias_key, limit)
        require_signed_payload(
            request,
            asdict(
                ListCatalogMetadataPayload(kind=kind, scope=scope, alias_key=alias_key, limit=limit)
            ),
        )
        initial = self.source.require_current(request, proofs)
        current = await require_online_owner_decision(self.source, self.current_owners, request)
        if not initial.same_epochs(current):
            raise AccessDenied("Catalog resource visibility permission changed")
        row_type = IntegrationRow if kind == "integrations" else VariableRow
        column = IntegrationRow.alias_key if kind == "integrations" else VariableRow.name_key
        filters = _metadata_filters(row_type, request, scope)
        if not filters:
            return ()
        query = select(row_type).where(or_(*filters), row_type.deleted_at.is_(None))
        if alias_key is not None:
            query = query.where(column == alias_key)
        # Strictly bounded even with both legal origins. No global alias
        # lookup, no default project wins over Team with equal names.
        query = query.order_by(row_type.id).limit(limit + 1)
        async with self.db.transaction() as tx:
            selected = list(await tx.scalars(query))
            if len(selected) > limit:
                raise Conflict("Catalog list exceeds bounded page; use scoped pagination")
        end = await require_online_owner_decision(self.source, self.current_owners, request)
        if not end.same_epochs(current):
            raise AccessDenied("Catalog permission revoked before listing response")
        result: list[CatalogResourceSummary] = []
        for row in selected:
            if not isinstance(row, (IntegrationRow, VariableRow)):
                raise AccessDenied("Catalog source row type differs from selected resource")
            result.append(_resource_summary(row, kind))
        if alias_key is not None and len(result) > 1:
            raise Conflict("Catalog alias ambiguous across Team and Project owners")
        return tuple(result)

    @staticmethod
    def _required_secret(value: SecretStr | None) -> SecretStr:
        if value is None:
            raise InvalidInput("Replacement secret required for rotation")
        return value

    async def create_variable(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        owner_scope: Literal["team", "project"],
        name: str,
        value: SecretStr,
        is_secret: bool,
    ) -> OwnerCommandOutcome[CatalogCreateVariable]:
        if decision.request.operation != "catalog.variable.create":
            raise InvalidInput("unapproved Catalog variable operation")
        owner = self._owner_fields(decision.request, owner_scope)
        key = canonical_variable_name(name)
        fingerprint = self._secret_digest(value)
        require_signed_payload(
            decision.request,
            asdict(
                CreateCatalogVariablePayload(
                    owner_scope=owner_scope,
                    owner_id=str(owner.team_id or owner.project_id),
                    name_key=key,
                    is_secret=is_secret,
                    value_hmac_sha256=fingerprint,
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> CatalogCreateVariable:
            active = await tx.scalar(
                select(VariableRow.id)
                .where(
                    VariableRow.owner_team_id == owner.team_id,
                    VariableRow.owner_project_id == owner.project_id,
                    VariableRow.name_key == key,
                    VariableRow.deleted_at.is_(None),
                )
                .limit(1)
            )
            if active is not None:
                raise Conflict("variable key already exists within selected owner")
            raw = value.get_secret_value()
            row = VariableRow(
                id=uuid4(),
                name_key=key,
                is_secret=is_secret,
                encrypted_value=self.cipher.encrypt(raw.encode()).decode() if is_secret else None,
                plain_value=None if is_secret else raw,
                version=1,
                owner_team_id=owner.team_id,
                owner_project_id=owner.project_id,
            )
            tx.add(row)
            return CatalogCreateVariable(
                resource_id=str(row.id),
                owner_scope=owner_scope,
                name_key=key,
                version=1,
                is_secret=is_secret,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="catalog.variable_created",
            target=key,
            response_model=CatalogCreateVariable,
        )

    async def change_integration(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        integration_id: UUID,
        owner_scope: Literal["team", "project"],
        expected_version: int,
        action: Literal["rotate", "revoke"],
        replacement_credential: SecretStr | None = None,
    ) -> OwnerCommandOutcome[CatalogChangeIntegration]:
        if (
            decision.request.operation != f"catalog.integration.{action}"
            or integration_id.version != 4
            or expected_version < 1
            or (action == "rotate") != (replacement_credential is not None)
        ):
            raise InvalidInput("integration rotation/revoke requires original owner intent")
        owner = self._owner_fields(decision.request, owner_scope)
        fingerprint = (
            self._secret_digest(replacement_credential)
            if replacement_credential is not None
            else None
        )
        require_signed_payload(
            decision.request,
            asdict(
                ChangeCatalogIntegrationPayload(
                    integration_id=str(integration_id),
                    owner_scope=owner_scope,
                    owner_id=str(owner.team_id or owner.project_id),
                    expected_version=expected_version,
                    action=action,
                    new_credential_hmac_sha256=fingerprint,
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> CatalogChangeIntegration:
            row = await tx.scalar(
                select(IntegrationRow)
                .where(
                    IntegrationRow.id == integration_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or row.deleted_at is not None
                or row.version != expected_version
                or row.owner_team_id != owner.team_id
                or row.owner_project_id != owner.project_id
            ):
                raise AccessDenied("Catalog integration owner or CAS revision changed")
            if action == "revoke":
                row.deleted_at = datetime.now(UTC)
            else:
                row.encrypted_credential = self.cipher.encrypt(
                    self._required_secret(replacement_credential).get_secret_value().encode()
                ).decode()
            row.version += 1
            row.updated_at = datetime.now(UTC)
            # Existing credential leases are immediately fenced by resource
            # version or deletion. No cross-DB token/group grants are minted.
            return CatalogChangeIntegration(
                resource_id=str(row.id),
                version=row.version,
                owner_scope=owner_scope,
                revoked=action == "revoke",
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event=f"catalog.integration_{'rotated' if action == 'rotate' else 'revoked'}",
            target=str(integration_id),
            response_model=CatalogChangeIntegration,
        )

    async def change_variable(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        variable_id: UUID,
        owner_scope: Literal["team", "project"],
        expected_version: int,
        action: Literal["rotate", "revoke"],
        replacement_value: SecretStr | None = None,
    ) -> OwnerCommandOutcome[CatalogChangeVariable]:
        if (
            decision.request.operation != f"catalog.variable.{action}"
            or variable_id.version != 4
            or expected_version < 1
            or (action == "rotate") != (replacement_value is not None)
        ):
            raise InvalidInput("variable rotation/revoke requires original owner intent")
        owner = self._owner_fields(decision.request, owner_scope)
        fingerprint = (
            self._secret_digest(replacement_value) if replacement_value is not None else None
        )
        require_signed_payload(
            decision.request,
            asdict(
                ChangeCatalogVariablePayload(
                    variable_id=str(variable_id),
                    owner_scope=owner_scope,
                    owner_id=str(owner.team_id or owner.project_id),
                    expected_version=expected_version,
                    action=action,
                    new_value_hmac_sha256=fingerprint,
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> CatalogChangeVariable:
            row = await tx.scalar(
                select(VariableRow)
                .where(
                    VariableRow.id == variable_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or row.deleted_at is not None
                or row.version != expected_version
                or row.owner_team_id != owner.team_id
                or row.owner_project_id != owner.project_id
            ):
                raise AccessDenied("Catalog variable owner or CAS revision changed")
            if action == "revoke":
                row.deleted_at = datetime.now(UTC)
            else:
                write_variable_content(row, self._required_secret(replacement_value), self.cipher)
            row.version += 1
            row.updated_at = datetime.now(UTC)
            return CatalogChangeVariable(
                resource_id=str(row.id),
                version=row.version,
                owner_scope=owner_scope,
                revoked=action == "revoke",
                is_secret=row.is_secret,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event=f"catalog.variable_{'rotated' if action == 'rotate' else 'revoked'}",
            target=str(variable_id),
            response_model=CatalogChangeVariable,
        )

    async def reserve_variable(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        variable_id: UUID,
        expected_resource_version: int,
        owner_scope: Literal["team", "project"],
        service_id: UUID,
        service_instance_uuid: UUID,
        service_audience: str,
        expires_in_seconds: int = 60,
    ) -> OwnerCommandOutcome[CatalogReserveVariable]:
        """One-use bound secret-variable lease, no values in returned DTO."""
        request = decision.request
        if (
            request.operation != "catalog.variable.reserve"
            or variable_id.version != 4
            or service_id.version != 4
            or service_instance_uuid.version != 4
            or expected_resource_version < 1
            or not service_audience.startswith("briareus:")
            or not 1 <= expires_in_seconds <= 60
        ):
            raise InvalidInput("secret variable lease parameters invalid")
        owner = self._owner_fields(request, owner_scope)
        owner_id = owner.owner_id
        require_signed_payload(
            request,
            asdict(
                ReserveVariablePayload(
                    variable_id=str(variable_id),
                    expected_resource_version=expected_resource_version,
                    owner_scope=owner_scope,
                    owner_id=str(owner_id),
                    service_id=str(service_id),
                    service_instance_uuid=str(service_instance_uuid),
                    service_audience=service_audience,
                    expires_in_seconds=expires_in_seconds,
                )
            ),
        )

        async def mutation(tx: AsyncSession) -> CatalogReserveVariable:
            variable = await tx.scalar(
                select(VariableRow).where(VariableRow.id == variable_id).with_for_update()
            )
            if (
                variable is None
                or variable.deleted_at is not None
                or variable.version != expected_resource_version
                or variable.owner_team_id != owner.team_id
                or variable.owner_project_id != owner.project_id
            ):
                raise AccessDenied("Catalog variable revoked or owner revision changed")
            expiry = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
            lease = CredentialLeaseRow(
                id=uuid4(),
                project_id=request.project_id,
                user_id=request.caller_user_id,
                session_uuid=request.session_uuid,
                resource_id=variable_id,
                kind="variable",
                owner_scope=owner_scope,
                owner_id=owner_id,
                resource_version=variable.version,
                service_id=service_id,
                service_instance_uuid=service_instance_uuid,
                operation_uuid=request.operation_uuid,
                service_audience=service_audience,
                correlation_id=request.operation_uuid,
                project_version=request.expected_control_revision,
                project_resource_revision=request.expected_control_resource_revision,
                team_version=request.expected_team_revision,
                team_resource_revision=request.expected_team_resource_revision,
                session_version=request.expected_access_revision,
                expires_at=expiry,
                redeemed_at=None,
            )
            tx.add(lease)
            return CatalogReserveVariable(
                lease_id=str(lease.id),
                owner_scope=owner_scope,
                owner_id=str(owner_id),
                resource_version=variable.version,
                expires_at=expiry.isoformat(),
                credential_configured=bool(variable.is_secret),
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="catalog.variable_lease_reserved",
            target=str(variable_id),
            response_model=CatalogReserveVariable,
        )

    def _variable_content(self, variable: VariableRow) -> str:
        try:
            if variable.is_secret:
                if variable.encrypted_value is None:
                    raise InvalidToken
                cleartext = self.cipher.decrypt(variable.encrypted_value.encode()).decode()
            else:
                if variable.plain_value is None:
                    raise InvalidToken
                cleartext = variable.plain_value
        except (InvalidToken, UnicodeDecodeError):
            raise AccessDenied("variable content integrity unavailable") from None
        return cleartext

    async def redeem_variable(
        self,
        request: OwnerCommandDTO,
        proofs: SignedOwnerProofs,
        *,
        lease_id: UUID,
        service_id: UUID,
        instance_uuid: UUID,
        audience: str,
        peer_evidence: object,
    ) -> SecretStr:
        """One-time confidential variable delivery strictly to attested peer."""
        if (
            request.target_owner != "resources"
            or request.operation != "catalog.variable.redeem"
            or any(value.version != 4 for value in (lease_id, service_id, instance_uuid))
        ):
            raise AccessDenied("variable redemption is not a reviewed owner operation")
        require_signed_payload(
            request,
            asdict(
                RedeemCatalogLeasePayload(
                    lease_id=str(lease_id),
                    service_id=str(service_id),
                    instance_uuid=str(instance_uuid),
                    audience=audience,
                )
            ),
        )
        try:
            peer = self.peer_verifier.verify_peer(peer_evidence)
            _require_peer_binding(
                peer, service_id, instance_uuid, audience, "variable lease peer identity changed"
            )
        except Exception:
            raise AccessDenied("trusted native variable consumer required") from None
        initial = self.source.require_current(request, proofs)
        fresh = await require_online_owner_decision(self.source, self.current_owners, request)
        if not initial.same_epochs(fresh):
            raise AccessDenied("variable source owner grant revoked")
        async with self.db.transaction() as tx:
            lease = await tx.scalar(
                select(CredentialLeaseRow)
                .where(CredentialLeaseRow.id == lease_id)
                .with_for_update()
            )
            if (
                lease is None
                or lease.kind != "variable"
                or lease.project_id != request.project_id
                or lease.session_uuid != request.session_uuid
                or lease.user_id != request.caller_user_id
                or lease.service_id != service_id
                or lease.service_instance_uuid != instance_uuid
                or lease.service_audience != audience
                or lease.redeemed_at is not None
                or lease.expires_at <= datetime.now(UTC)
                or lease.session_version != request.expected_access_revision
                or lease.project_version != request.expected_control_revision
                or lease.project_resource_revision != request.expected_control_resource_revision
                or lease.team_version != request.expected_team_revision
                or lease.team_resource_revision != request.expected_team_resource_revision
            ):
                raise AccessDenied("variable lease consumed, expired or owner changed")
            variable = await tx.scalar(
                select(VariableRow).where(VariableRow.id == lease.resource_id).with_for_update()
            )
            if (
                variable is None
                or variable.deleted_at is not None
                or variable.version != lease.resource_version
                or (lease.owner_scope == "team" and variable.owner_team_id != lease.owner_id)
                or (lease.owner_scope == "project" and variable.owner_project_id != lease.owner_id)
            ):
                raise AccessDenied("variable source revision fenced or disabled")
            cleartext = self._variable_content(variable)
            current = await require_online_owner_decision(self.source, self.current_owners, request)
            if not fresh.same_epochs(current):
                raise AccessDenied("variable source proof revoked before consume")
            lease.redeemed_at = datetime.now(UTC)
            tx.add(
                OwnerAuditRow(
                    operation_uuid=request.operation_uuid,
                    actor_user_id=request.caller_user_id,
                    project_id=request.project_id,
                    action="catalog.variable_redeemed",
                    object_id=str(lease.id),
                    owner_revision=str(request.expected_control_resource_revision),
                    details=ResourceAccessAudit(resource_id=variable.id, service_id=service_id),
                )
            )
            tx.add(
                OwnerOutboxRow(
                    operation_uuid=request.operation_uuid,
                    event_name="catalog.variable_redeemed",
                    owner_revision=str(request.expected_control_resource_revision),
                    event_payload=VariableCredentialRedeemed(
                        lease_id=lease.id,
                        resource_id=variable.id,
                        operation_uuid=request.operation_uuid,
                    ),
                )
            )
            return SecretStr(cleartext)
