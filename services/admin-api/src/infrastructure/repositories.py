from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from domain.configuration import AdminConfig
from domain.telemetry import (
    Invocation,
    InvocationPage,
    InvocationQuery,
    InvocationSummary,
    require_invocation_status,
)
from opentelemetry import trace
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)

from ._adapter_resources import _SqlAlchemyRepository
from .account_repository import SqlAlchemyAccountRepository as SqlAlchemyAccountRepository
from .database import (
    AdminConfigRecord,
    BrowserRuntimeSettingsRecord,
    GitHubRuntimeSettingsRecord,
    GitLabRuntimeSettingsRecord,
    InvocationRecord,
    McpRuntimeSettingsRecord,
    RuntimeSettingsRecord,
)
from .database_spans import db_span as _db_span
from .oauth_session_repository import (
    SqlAlchemyOAuthSessionRepository as SqlAlchemyOAuthSessionRepository,
)
from .snapshot_repository import SqlAlchemySnapshotRepository as SqlAlchemySnapshotRepository


class SqlAlchemyInvocationRepository(_SqlAlchemyRepository):
    @staticmethod
    async def _config(session: AsyncSession) -> AdminConfigRecord:
        config = await session.get(AdminConfigRecord, 1)
        if config is None:
            config = AdminConfigRecord(id=1)
            session.add(config)
            await session.flush()
        return config

    @staticmethod
    async def _cleanup_in_session(session: AsyncSession, config: AdminConfigRecord) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=max(config.logging_retention_days, 1))
        removed_result = await session.execute(
            delete(InvocationRecord).where(InvocationRecord.occurred_at < cutoff)
        )
        if not isinstance(removed_result, CursorResult):
            raise RuntimeError(
                "invocation retention cleanup returned an unsupported execution result"
            )
        removed = removed_result.rowcount or 0
        count = await session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
        overflow = count - max(config.logging_max_records, 100)
        if overflow > 0:
            stale_ids = (
                select(InvocationRecord.id)
                .order_by(InvocationRecord.occurred_at.asc())
                .limit(overflow)
            )
            overflow_result = await session.execute(
                delete(InvocationRecord).where(InvocationRecord.id.in_(stale_ids))
            )
            if not isinstance(overflow_result, CursorResult):
                raise RuntimeError(
                    "invocation overflow cleanup returned an unsupported execution result"
                )
            removed += overflow_result.rowcount or 0
        return int(removed)

    @staticmethod
    def _record(invocation: Invocation, *, capture_payloads: bool) -> InvocationRecord:
        visible = invocation.captured(capture_payloads)
        return InvocationRecord(
            id=visible.id,
            request_id=visible.request_id,
            module=visible.module,
            tool=visible.tool,
            account_id=visible.account_id,
            provider=visible.provider,
            status=visible.status,
            duration_ms=visible.duration_ms,
            error_type=visible.error_type,
            arguments_json=visible.arguments_json,
            result_json=visible.result_json,
            error_message=visible.error_message,
            occurred_at=visible.occurred_at,
        )

    async def append(self, invocation: Invocation, *, capture_payloads: bool = True) -> None:
        await self.append_many([invocation], capture_payloads=capture_payloads)

    @_db_span("audit.append_many")
    async def append_many(
        self,
        invocations: Sequence[Invocation],
        *,
        capture_payloads: bool = True,
    ) -> None:
        if not invocations:
            return
        trace.get_current_span().set_attribute("db.batch.size", len(invocations))
        async with self.sessions.begin() as session:
            session.add_all(
                [
                    self._record(invocation, capture_payloads=capture_payloads)
                    for invocation in invocations
                ]
            )

    @staticmethod
    def _invocation(row: InvocationRecord) -> Invocation:
        status = row.status
        require_invocation_status(status)
        return Invocation(
            id=row.id,
            request_id=row.request_id,
            module=row.module,
            tool=row.tool,
            account_id=row.account_id,
            provider=row.provider,
            status="success" if status == "success" else "error",
            duration_ms=row.duration_ms,
            error_type=row.error_type,
            arguments_json=row.arguments_json,
            result_json=row.result_json,
            error_message=row.error_message,
            occurred_at=row.occurred_at,
        )

    async def query(self, query: InvocationQuery) -> InvocationPage:
        filters: list[ColumnElement[bool]] = []
        if query.module:
            filters.append(InvocationRecord.module == query.module)
        if query.tool:
            filters.append(InvocationRecord.tool == query.tool)
        if query.provider:
            filters.append(InvocationRecord.provider == query.provider)
        if query.account_id:
            filters.append(InvocationRecord.account_id == query.account_id)
        if query.status is not None:
            filters.append(InvocationRecord.status == query.status)
        if query.search:
            pattern = f"%{query.search.strip()}%"
            filters.append(
                or_(
                    InvocationRecord.module.ilike(pattern),
                    InvocationRecord.tool.ilike(pattern),
                    InvocationRecord.request_id.ilike(pattern),
                    InvocationRecord.provider.ilike(pattern),
                    InvocationRecord.account_id.ilike(pattern),
                )
            )

        async with self.sessions() as session:
            total = (
                await session.scalar(
                    select(func.count()).select_from(InvocationRecord).where(*filters)
                )
                or 0
            )
            stmt = select(InvocationRecord).where(*filters)
            if query.cursor_at is not None and query.cursor_id:
                stmt = stmt.where(
                    or_(
                        InvocationRecord.occurred_at < query.cursor_at,
                        and_(
                            InvocationRecord.occurred_at == query.cursor_at,
                            InvocationRecord.id < query.cursor_id,
                        ),
                    )
                )
            elif query.offset:
                stmt = stmt.offset(query.offset)
            rows = (
                await session.scalars(
                    stmt.order_by(
                        InvocationRecord.occurred_at.desc(), InvocationRecord.id.desc()
                    ).limit(query.limit + 1)
                )
            ).all()

        has_more = len(rows) > query.limit
        visible = rows[: query.limit]
        events = [self._invocation(row) for row in visible]
        tail = visible[-1] if visible and has_more else None
        return InvocationPage(
            events=events,
            total=int(total),
            count=len(events),
            has_more=has_more,
            next_cursor_at=tail.occurred_at if tail is not None else None,
            next_cursor_id=tail.id if tail is not None else "",
        )

    async def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return (await self.query(InvocationQuery(limit=max(1, min(limit, 500))))).events

    async def clear(self) -> int:
        async with self.sessions.begin() as session:
            count = await session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
            await session.execute(delete(InvocationRecord))
            return int(count)

    async def delete(self, invocation_id: str) -> bool:
        async with self.sessions.begin() as session:
            result = await session.execute(
                delete(InvocationRecord).where(InvocationRecord.id == invocation_id)
            )
            if not isinstance(result, CursorResult):
                raise RuntimeError("invocation deletion returned an unsupported execution result")
            return bool(result.rowcount)

    async def summary(self) -> InvocationSummary:
        async with self.sessions() as session:
            total = await session.scalar(select(func.count()).select_from(InvocationRecord)) or 0
            errors = (
                await session.scalar(
                    select(func.count())
                    .select_from(InvocationRecord)
                    .where(InvocationRecord.status == "error")
                )
                or 0
            )
            average = await session.scalar(select(func.avg(InvocationRecord.duration_ms))) or 0.0
        return InvocationSummary(
            total=int(total),
            errors=int(errors),
            error_rate=round((float(errors) * 100.0 / float(total)), 1) if total else 0.0,
            average_duration_ms=round(float(average), 1),
        )

    @_db_span("audit.cleanup")
    async def cleanup(self) -> int:
        async with self.sessions.begin() as session:
            return await self._cleanup_in_session(session, await self._config(session))


class SqlAlchemyAdminConfigRepository(_SqlAlchemyRepository):
    @staticmethod
    def _domain(record: AdminConfigRecord) -> AdminConfig:
        return AdminConfig(
            logging_enabled=record.logging_enabled,
            logging_capture_payloads=record.logging_capture_payloads,
            logging_retention_days=record.logging_retention_days,
            logging_max_records=record.logging_max_records,
            maintenance_interval_minutes=record.maintenance_interval_minutes,
        )

    @_db_span("config.get")
    async def get(self) -> AdminConfig:
        async with self.sessions.begin() as session:
            record = await session.get(AdminConfigRecord, 1)
            if record is None:
                record = AdminConfigRecord(id=1)
                session.add(record)
                await session.flush()
            return self._domain(record)

    @_db_span("config.save")
    async def save(self, config: AdminConfig) -> AdminConfig:
        async with self.sessions.begin() as session:
            record = await session.get(AdminConfigRecord, 1)
            if record is None:
                record = AdminConfigRecord(id=1)
                session.add(record)
            record.logging_enabled = config.logging_enabled
            record.logging_capture_payloads = config.logging_capture_payloads
            record.logging_retention_days = config.logging_retention_days
            record.logging_max_records = config.logging_max_records
            record.maintenance_interval_minutes = config.maintenance_interval_minutes
        return config


class SqlAlchemyRuntimeSettingsRepository(_SqlAlchemyRepository):
    @staticmethod
    def _domain(record: RuntimeSettingsRecord) -> TerminalRuntimePolicy:
        return TerminalRuntimePolicy(
            max_exec_timeout_seconds=record.terminal_max_exec_timeout_seconds,
            max_job_runtime_seconds=record.terminal_max_job_runtime_seconds,
        )

    @_db_span("runtime.terminal.get")
    async def get_terminal_policy(self) -> TerminalRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(RuntimeSettingsRecord, 1)
            if record is None:
                record = RuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            elif (
                record.terminal_max_exec_timeout_seconds == 300
                and record.terminal_max_job_runtime_seconds == 3600
            ):
                record.terminal_max_exec_timeout_seconds = 21_600
                record.terminal_max_job_runtime_seconds = 43_200
                await session.flush()
            return self._domain(record)

    @_db_span("runtime.terminal.save")
    async def save_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(RuntimeSettingsRecord, 1)
            if record is None:
                record = RuntimeSettingsRecord(id=1)
                session.add(record)
            record.terminal_max_exec_timeout_seconds = policy.max_exec_timeout_seconds
            record.terminal_max_job_runtime_seconds = policy.max_job_runtime_seconds
        return policy

    @_db_span("runtime.mcp.get")
    async def get_mcp_policy(self) -> McpRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(McpRuntimeSettingsRecord, 1)
            if record is None:
                record = McpRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return McpRuntimePolicy(call_timeout_seconds=record.call_timeout_seconds)

    @_db_span("runtime.mcp.save")
    async def save_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        if policy.call_timeout_seconds is None:
            raise ValueError("Legacy runtime settings storage requires a numeric MCP call timeout")
        async with self.sessions.begin() as session:
            record = await session.get(McpRuntimeSettingsRecord, 1)
            if record is None:
                record = McpRuntimeSettingsRecord(id=1)
                session.add(record)
            record.call_timeout_seconds = policy.call_timeout_seconds
        return policy

    @_db_span("runtime.github.get")
    async def get_github_policy(self) -> GitHubRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitHubRuntimeSettingsRecord, 1)
            if record is None:
                record = GitHubRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return GitHubRuntimePolicy(
                local_first_guidance=record.local_first_guidance,
                local_git_transport_enabled=record.local_git_transport_enabled,
                remote_source_mutations_enabled=record.remote_source_mutations_enabled,
            )

    @_db_span("runtime.github.save")
    async def save_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitHubRuntimeSettingsRecord, 1)
            if record is None:
                record = GitHubRuntimeSettingsRecord(id=1)
                session.add(record)
            record.local_first_guidance = policy.local_first_guidance
            record.local_git_transport_enabled = policy.local_git_transport_enabled
            record.remote_source_mutations_enabled = policy.remote_source_mutations_enabled
        return policy

    @_db_span("runtime.gitlab.get")
    async def get_gitlab_policy(self) -> GitLabRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitLabRuntimeSettingsRecord, 1)
            if record is None:
                record = GitLabRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return GitLabRuntimePolicy(
                local_first_guidance=record.local_first_guidance,
                local_git_transport_enabled=record.local_git_transport_enabled,
                remote_source_mutations_enabled=record.remote_source_mutations_enabled,
            )

    @_db_span("runtime.gitlab.save")
    async def save_gitlab_policy(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(GitLabRuntimeSettingsRecord, 1)
            if record is None:
                record = GitLabRuntimeSettingsRecord(id=1)
                session.add(record)
            record.local_first_guidance = policy.local_first_guidance
            record.local_git_transport_enabled = policy.local_git_transport_enabled
            record.remote_source_mutations_enabled = policy.remote_source_mutations_enabled
        return policy

    @staticmethod
    def _browser_domain(record: BrowserRuntimeSettingsRecord) -> BrowserRuntimePolicy:
        return BrowserRuntimePolicy(
            external_enabled=record.external_enabled,
            external_mcp_url=record.external_mcp_url,
            call_timeout_seconds=record.call_timeout_seconds,
            auto_disconnect_enabled=record.auto_disconnect_enabled,
            idle_timeout_seconds=record.idle_timeout_seconds,
            profile_dir_name=record.profile_dir_name,
            extension_token_configured=bool(record.encrypted_extension_token),
        )

    @_db_span("runtime.browser.get")
    async def get_browser_policy(self) -> BrowserRuntimePolicy:
        async with self.sessions.begin() as session:
            record = await session.get(BrowserRuntimeSettingsRecord, 1)
            if record is None:
                record = BrowserRuntimeSettingsRecord(id=1)
                session.add(record)
                await session.flush()
            return self._browser_domain(record)

    @_db_span("runtime.browser.save")
    async def save_browser_policy(
        self,
        policy: BrowserRuntimePolicy,
        *,
        encrypted_extension_token: str | None = None,
        clear_extension_token: bool = False,
    ) -> BrowserRuntimePolicy:
        if policy.call_timeout_seconds is None:
            raise ValueError(
                "Legacy runtime settings storage requires a numeric browser call timeout"
            )
        async with self.sessions.begin() as session:
            record = await session.get(BrowserRuntimeSettingsRecord, 1)
            if record is None:
                record = BrowserRuntimeSettingsRecord(id=1)
                session.add(record)
            record.external_enabled = policy.external_enabled
            record.external_mcp_url = policy.external_mcp_url
            record.call_timeout_seconds = policy.call_timeout_seconds
            record.auto_disconnect_enabled = policy.auto_disconnect_enabled
            record.idle_timeout_seconds = policy.idle_timeout_seconds
            record.profile_dir_name = policy.profile_dir_name
            if clear_extension_token:
                record.encrypted_extension_token = ""
            elif encrypted_extension_token is not None:
                record.encrypted_extension_token = encrypted_extension_token
            await session.flush()
            return self._browser_domain(record)

    @_db_span("runtime.browser.token")
    async def browser_extension_token(self) -> str:
        async with self.sessions.begin() as session:
            record = await session.get(BrowserRuntimeSettingsRecord, 1)
            if record is None or not record.encrypted_extension_token:
                return ""
            return str(record.encrypted_extension_token)
