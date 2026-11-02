"""Provider-specific account SQL stays inside the Admin API storage adapter."""

from collections.abc import Sequence
from datetime import UTC, datetime

from domain.accounts import Account, AccountConflictError, AuthType, Provider
from sqlalchemy import Select, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from ._adapter_resources import _SqlAlchemyRepository
from .database import (
    CoolifyAccountRecord,
    GitHubAccountRecord,
    GitLabAccountRecord,
    SigNozAccountRecord,
)
from .database_spans import db_span as _db_span

type AccountRecord = (
    GitHubAccountRecord | GitLabAccountRecord | SigNozAccountRecord | CoolifyAccountRecord
)


def provider_model(provider: Provider) -> type[AccountRecord]:
    if provider is Provider.GITHUB:
        return GitHubAccountRecord
    if provider is Provider.GITLAB:
        return GitLabAccountRecord
    if provider is Provider.SIGNOZ:
        return SigNozAccountRecord
    return CoolifyAccountRecord


async def provider_records[Record: AccountRecord](
    session: AsyncSession, model: type[Record], *, enabled_only: bool
) -> Sequence[Record]:
    statement = select(model)
    if enabled_only:
        statement = statement.where(model.enabled.is_(True))
    return (await session.scalars(statement)).all()


def selector_statement[Record: AccountRecord](
    model: type[Record], value: str, *, enabled_only: bool
) -> Select[tuple[Record]]:
    statement = select(model).where(or_(model.id == value, model.alias == value.casefold()))
    return statement.where(model.enabled.is_(True)) if enabled_only else statement


async def selected_record(
    session: AsyncSession, provider: Provider, value: str, *, enabled_only: bool
) -> AccountRecord | None:
    if provider is Provider.GITHUB:
        return (
            await session.scalars(
                selector_statement(GitHubAccountRecord, value, enabled_only=enabled_only)
            )
        ).first()
    if provider is Provider.GITLAB:
        return (
            await session.scalars(
                selector_statement(GitLabAccountRecord, value, enabled_only=enabled_only)
            )
        ).first()
    if provider is Provider.SIGNOZ:
        return (
            await session.scalars(
                selector_statement(SigNozAccountRecord, value, enabled_only=enabled_only)
            )
        ).first()
    return (
        await session.scalars(
            selector_statement(CoolifyAccountRecord, value, enabled_only=enabled_only)
        )
    ).first()


async def record_by_id(
    session: AsyncSession, provider: Provider, account_id: str
) -> AccountRecord | None:
    if provider is Provider.GITHUB:
        return await session.get(GitHubAccountRecord, account_id)
    if provider is Provider.GITLAB:
        return await session.get(GitLabAccountRecord, account_id)
    if provider is Provider.SIGNOZ:
        return await session.get(SigNozAccountRecord, account_id)
    return await session.get(CoolifyAccountRecord, account_id)


class SqlAlchemyAccountRepository(_SqlAlchemyRepository):
    @staticmethod
    def _github_domain(record: GitHubAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITHUB,
            auth_type=AuthType(record.auth_type),
            base_url="https://api.github.com",
            external_id=record.app_id,
            verify_tls=True,
            ca_cert_pem="",
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _gitlab_domain(record: GitLabAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.GITLAB,
            auth_type=AuthType(record.auth_type),
            base_url=record.base_url,
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _signoz_domain(record: SigNozAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.SIGNOZ,
            auth_type=AuthType(record.auth_type),
            base_url=record.base_url,
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _coolify_domain(record: CoolifyAccountRecord) -> Account:
        return Account(
            id=record.id,
            alias=record.alias,
            provider=Provider.COOLIFY,
            auth_type=AuthType(record.auth_type),
            base_url=record.base_url,
            verify_tls=record.verify_tls,
            ca_cert_pem=record.ca_cert_pem,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @_db_span("accounts.list")
    async def list(
        self, *, provider: Provider | None = None, enabled_only: bool = True
    ) -> Sequence[Account]:
        accounts: list[Account] = []
        async with self.sessions() as session:
            for current in Provider:
                if provider is not None and current != provider:
                    continue
                rows = await provider_records(
                    session, provider_model(current), enabled_only=enabled_only
                )
                accounts.extend(self._domain(row) for row in rows)
        return sorted(accounts, key=lambda item: (item.provider.value, item.alias))

    @_db_span("accounts.get")
    async def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        value = selector.strip()
        if not value:
            raise KeyError("account selector is required")
        async with self.sessions() as session:
            record = await selected_record(session, provider, value, enabled_only=enabled_only)
            if record is None:
                provider_label = {
                    Provider.GITHUB: "GitHub",
                    Provider.GITLAB: "GitLab",
                    Provider.SIGNOZ: "SigNoz",
                    Provider.COOLIFY: "Coolify",
                }[provider]
                raise KeyError(f"{provider_label} account not found: {selector}")
            return self._domain(record)

    def _domain(self, record: AccountRecord) -> Account:
        if isinstance(record, GitHubAccountRecord):
            return self._github_domain(record)
        if isinstance(record, GitLabAccountRecord):
            return self._gitlab_domain(record)
        if isinstance(record, SigNozAccountRecord):
            return self._signoz_domain(record)
        return self._coolify_domain(record)

    @_db_span("accounts.save")
    async def save(
        self,
        account: Account,
        *,
        encrypted_credential: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> Account:
        if expected_updated_at is not None:
            await self._save_if_current(account, encrypted_credential, expected_updated_at)
        else:
            await self._save_unversioned(account, encrypted_credential)
        return account

    async def _save_if_current(
        self, account: Account, encrypted_credential: str | None, expected_updated_at: datetime
    ) -> None:
        model = provider_model(account.provider)
        statement = (
            update(model)
            .where(model.id == account.id, model.updated_at == expected_updated_at)
            .values(
                alias=account.alias,
                auth_type=account.auth_type.value,
                enabled=account.enabled,
                updated_at=account.updated_at,
            )
        )
        if account.provider is Provider.GITHUB:
            statement = statement.values(app_id=account.external_id)
        else:
            statement = statement.values(
                base_url=account.base_url,
                verify_tls=account.verify_tls,
                ca_cert_pem=account.ca_cert_pem,
            )
        if encrypted_credential is not None:
            statement = statement.values(encrypted_credential=encrypted_credential)
        async with self.sessions.begin() as session:
            result = await session.execute(statement)
            if not isinstance(result, CursorResult):
                raise RuntimeError("account update returned an unsupported execution result")
            if result.rowcount != 1:
                raise AccountConflictError("account changed since it was loaded")

    async def _save_unversioned(self, account: Account, encrypted_credential: str | None) -> None:
        async with self.sessions.begin() as session:
            record = await record_by_id(session, account.provider, account.id)
            if record is None:
                record = provider_model(account.provider)(id=account.id)
            session.add(record)
            if isinstance(record, GitHubAccountRecord):
                record.app_id = account.external_id
            else:
                record.base_url = account.base_url
                record.verify_tls = account.verify_tls
                record.ca_cert_pem = account.ca_cert_pem
            record.alias = account.alias
            record.auth_type = account.auth_type.value
            record.enabled = account.enabled
            record.created_at = account.created_at
            record.updated_at = account.updated_at
            if encrypted_credential is not None:
                record.encrypted_credential = encrypted_credential

    @_db_span("accounts.delete")
    async def delete(self, account_id: str, *, provider: Provider) -> None:
        async with self.sessions.begin() as session:
            record = await record_by_id(session, provider, account_id)
            if record is not None:
                await session.delete(record)

    @_db_span("accounts.set_credential")
    async def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None:
        async with self.sessions.begin() as session:
            record = await record_by_id(session, provider, account_id)
            if record is None:
                raise KeyError(f"account not found: {account_id}")
            record.encrypted_credential = encrypted_value
            record.updated_at = datetime.now(UTC)

    @_db_span("accounts.credential")
    async def credential(self, account_id: str, *, provider: Provider) -> str:
        async with self.sessions() as session:
            record = await record_by_id(session, provider, account_id)
            if record is None or not record.encrypted_credential:
                raise KeyError(f"credential not configured for account: {account_id}")
            return str(record.encrypted_credential)
