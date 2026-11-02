"""Owner SQL/Fernet adapters and the external runtime policy representation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import MISSING
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from node_protocol.models import ModuleConfiguration, RuntimePolicy, RuntimePolicyOverrides
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import NodeRow, RuntimePolicyRow
from projects.application.runtime_settings import RuntimePolicyReceipt, RuntimeSettingsSession
from projects.domain.runtime_settings import (
    EffectiveSetting,
    RuntimeOverride,
    RuntimeOverrides,
    RuntimePolicyConflict,
    RuntimePolicyIdentity,
    RuntimePolicyView,
    RuntimeResolution,
    RuntimeScope,
    RuntimeSetting,
    RuntimeSource,
    StoredRuntimePolicy,
    resolve_runtime,
)
from projects.infrastructure._session_bindings import _CipherSessionBinding
from projects.infrastructure.audit_records import RuntimeSettingsAudit
from service_runtime.platform_db_mechanics import _DatabaseCipherBinding


class RuntimeSources(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    execution_timeout_seconds: RuntimeSource
    web_max_tabs: RuntimeSource
    web_tab_idle_seconds: RuntimeSource
    terminal_idle_seconds: RuntimeSource

    def __getitem__(self, key: str) -> RuntimeSource:
        match key:
            case "execution_timeout_seconds":
                return self.execution_timeout_seconds
            case "web_max_tabs":
                return self.web_max_tabs
            case "web_tab_idle_seconds":
                return self.web_tab_idle_seconds
            case "terminal_idle_seconds":
                return self.terminal_idle_seconds
            case _:
                raise KeyError(key)


class RuntimePolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scope: RuntimeScope
    node_uuid: UUID | None
    sequence: int = Field(strict=True, ge=0)
    overrides: RuntimePolicyOverrides
    effective: RuntimePolicy
    sources: RuntimeSources
    applies_on: Literal["placement_update"] = "placement_update"

    @classmethod
    def from_view(cls, view: RuntimePolicyView) -> "RuntimePolicyPayload":
        return cls(
            scope=view.scope,
            node_uuid=view.node_uuid,
            sequence=view.sequence,
            overrides=override_payload(view.overrides),
            effective=effective_payload(view.effective),
            sources=source_payload(view.effective),
        )

    def record(self) -> RuntimePolicyView:
        effective = RuntimeResolution(
            (
                EffectiveSetting(
                    RuntimeSetting.EXECUTION_TIMEOUT,
                    self.effective.execution_timeout_seconds,
                    self.sources.execution_timeout_seconds,
                ),
                EffectiveSetting(
                    RuntimeSetting.WEB_MAX_TABS,
                    self.effective.web_max_tabs,
                    self.sources.web_max_tabs,
                ),
                EffectiveSetting(
                    RuntimeSetting.WEB_TAB_IDLE,
                    self.effective.web_tab_idle_seconds,
                    self.sources.web_tab_idle_seconds,
                ),
                EffectiveSetting(
                    RuntimeSetting.TERMINAL_IDLE,
                    self.effective.terminal_idle_seconds,
                    self.sources.terminal_idle_seconds,
                ),
            )
        )
        return RuntimePolicyView(
            self.scope, self.node_uuid, self.sequence, override_record(self.overrides), effective
        )


class RuntimePolicyEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    runtime_policy: RuntimePolicyPayload


def override_record(payload: RuntimePolicyOverrides) -> RuntimeOverrides:
    candidates = (
        (RuntimeSetting.EXECUTION_TIMEOUT, payload.execution_timeout_seconds),
        (RuntimeSetting.WEB_MAX_TABS, payload.web_max_tabs),
        (RuntimeSetting.WEB_TAB_IDLE, payload.web_tab_idle_seconds),
        (RuntimeSetting.TERMINAL_IDLE, payload.terminal_idle_seconds),
    )
    return RuntimeOverrides(
        tuple(
            RuntimeOverride(setting, value) for setting, value in candidates if value is not MISSING
        )
    )


def override_payload(overrides: RuntimeOverrides) -> RuntimePolicyOverrides:
    return RuntimePolicyOverrides.model_validate(
        {entry.setting.value: entry.value for entry in overrides.entries}
    )


def stored_overrides(row: RuntimePolicyRow | None) -> RuntimeOverrides:
    payload = row.values if row is not None else RuntimePolicyOverrides()
    return override_record(payload)


def effective_payload(resolution: RuntimeResolution) -> RuntimePolicy:
    return RuntimePolicy.model_validate(
        {entry.setting.value: entry.value for entry in resolution.entries}
    )


def source_payload(resolution: RuntimeResolution) -> RuntimeSources:
    return RuntimeSources.model_validate(
        {entry.setting.value: entry.source for entry in resolution.entries}
    )


async def resolved_configuration(
    tx: AsyncSession, node_uuid: UUID, configuration: ModuleConfiguration | None
) -> ModuleConfiguration | None:
    server = await tx.get(RuntimePolicyRow, "server")
    node = await tx.get(RuntimePolicyRow, "node:" + str(node_uuid))
    if server is None and node is None:
        return configuration
    resolution = resolve_runtime(
        stored_overrides(server),
        stored_overrides(node),
    )
    original = configuration if configuration is not None else ModuleConfiguration()
    return original.model_copy(update={"runtime_policy": effective_payload(resolution)})


class SqlRuntimeSettingsTransactions(_DatabaseCipherBinding[PlatformDatabase, Fernet]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[RuntimeSettingsSession]:
        async with self._database.transaction() as tx:
            yield SqlRuntimeSettingsSession(tx, self._cipher)


class SqlRuntimeSettingsSession(_CipherSessionBinding):
    async def lock(self, key: str) -> StoredRuntimePolicy | None:
        await self._tx.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": "runtime-policy:" + key},
        )
        row = await self._tx.scalar(
            select(RuntimePolicyRow).where(RuntimePolicyRow.scope_key == key).with_for_update()
        )
        return policy_record(row) if row else None

    async def node_exists(self, node_uuid: UUID) -> bool:
        node = await self._tx.get(NodeRow, node_uuid)
        return node is not None and node.deleted_at is None

    async def get(self, key: str) -> StoredRuntimePolicy | None:
        row = await self._tx.get(RuntimePolicyRow, key)
        return policy_record(row) if row else None

    async def receipt(self, operation_uuid: UUID) -> RuntimePolicyReceipt | None:
        row = await self._tx.scalar(
            select(OwnerCommandRow).where(
                OwnerCommandRow.operation_uuid == operation_uuid,
                OwnerCommandRow.operation == "node.runtime_policy",
            )
        )
        return (
            RuntimePolicyReceipt(
                row.fingerprint, row.actor_scope, row.project_scope, row.encrypted_outcome
            )
            if row
            else None
        )

    def replay(self, receipt: RuntimePolicyReceipt) -> RuntimePolicyView:
        if receipt.encrypted_outcome is None:
            raise RuntimePolicyConflict("Operation receipt unavailable")
        plaintext = self._cipher.decrypt(receipt.encrypted_outcome.encode())
        return RuntimePolicyEnvelope.model_validate_json(plaintext).runtime_policy.record()

    async def save(self, key: str, policy: StoredRuntimePolicy) -> None:
        row = await self._tx.get(RuntimePolicyRow, key)
        if row is None:
            row = RuntimePolicyRow(scope_key=key)
            self._tx.add(row)
        row.values = override_payload(policy.overrides)
        row.sequence = policy.sequence
        await self._tx.flush()

    async def complete(
        self, identity: RuntimePolicyIdentity, key: str, view: RuntimePolicyView, now: datetime
    ) -> None:
        payload = RuntimePolicyEnvelope(runtime_policy=RuntimePolicyPayload.from_view(view))
        self._tx.add(
            OwnerCommandRow(
                operation_uuid=identity.operation_uuid,
                actor_scope=str(identity.actor_uuid),
                project_scope=str(identity.project_uuid),
                operation="node.runtime_policy",
                key=str(identity.operation_uuid),
                fingerprint=identity.fingerprint,
                expected_owner_revision=str(identity.expected_sequence),
                state="completed",
                encrypted_outcome=self._cipher.encrypt(payload.model_dump_json().encode()).decode(),
                expires_at=now + timedelta(days=7),
            )
        )
        self._tx.add(
            OwnerAuditRow(
                operation_uuid=identity.operation_uuid,
                actor_user_id=identity.actor_uuid,
                project_id=identity.project_uuid,
                action="node.runtime_policy",
                object_id=key,
                owner_revision=str(view.sequence),
                details=RuntimeSettingsAudit(
                    keys=tuple(entry.setting for entry in view.overrides.entries)
                ),
            )
        )


def policy_record(row: RuntimePolicyRow) -> StoredRuntimePolicy:
    return StoredRuntimePolicy(row.sequence, stored_overrides(row))
