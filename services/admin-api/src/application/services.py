from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from domain.accounts import Account, Provider
from domain.analysis import CoverageRequest
from domain.configuration import AdminConfig
from domain.oauth_sessions import OAuthSession
from domain.realtime import AccountIdentity, AccountVerified
from domain.snapshots import SnapshotCategory
from domain.telemetry import (
    Invocation,
    InvocationBatch,
    InvocationPage,
    InvocationQuery,
    InvocationSummary,
)

from application.snapshot_contracts import AdminSnapshot, SnapshotContent
from common.account_contracts import AccountList, AccountPublic, ResolvedAccount
from common.cache_contracts import CacheBackend, CacheKeys
from common.oauth_session_contracts import OAuthSessionEvent
from common.runtime_policy_contracts import (
    BrowserLauncherPolicy,
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)
from common.settings import ValkeySettings
from service_runtime._repository_binding import _RepositoryBinding

from .account_views import public_account
from .configuration_document import AdminConfigDocument
from .ports import (
    AccountRepository,
    AdminConfigRepository,
    ConnectionVerifier,
    CredentialCipher,
    InvocationRepository,
    OAuthSessionRepository,
    RuntimeSettingsRepository,
    SnapshotRepository,
)
from .provider_verification import ConnectionVerification
from .realtime_details import RealtimeDetails, RealtimePublisher


class AccountService:
    def __init__(
        self,
        repository: AccountRepository,
        cipher: CredentialCipher,
        verifier: ConnectionVerifier,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
        publisher: RealtimePublisher | None = None,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.verifier = verifier
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None
        self.publisher = publisher

    def publish(self, event_type: str, data: RealtimeDetails) -> None:
        if self.publisher is not None:
            self.publisher("admin.events", event_type, data)

    def invalidate(self, account: Account) -> None:
        if self.cache is None or self.cache_keys is None:
            return
        self.cache.delete(
            *self.cache_keys.account_invalidation_keys(
                account.provider.value,
                account_id=account.id,
                alias=account.alias,
            )
        )

    async def list(self, *, provider: Provider | None = None) -> list[AccountPublic]:
        provider_key = provider.value if provider is not None else ""
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.account_list(provider_key), AccountList)
            if cached is not None:
                return cached.accounts

        accounts = [
            public_account(account)
            for account in await self.repository.list(provider=provider, enabled_only=False)
        ]
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.account_list(provider_key),
                AccountList(accounts=accounts, count=len(accounts)),
                ttl_seconds=self.cache_settings.account_list_ttl_seconds,
            )
        return accounts

    async def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account:
        return await self.repository.get(selector, provider=provider, enabled_only=enabled_only)

    async def resolve(self, selector: str, *, provider: Provider) -> ResolvedAccount:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(
                self.cache_keys.account(provider.value, selector), ResolvedAccount
            )
            if cached is not None:
                return cached

        account = await self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(
            await self.repository.credential(account.id, provider=provider)
        )
        resolved = ResolvedAccount.from_public(public_account(account), credential)
        if self.cache is not None and self.cache_keys is not None:
            selectors = {selector.casefold(), account.id.casefold(), account.alias.casefold()}
            for resolved_selector in selectors:
                self.cache.set_model(
                    self.cache_keys.account(provider.value, resolved_selector),
                    resolved,
                    ttl_seconds=self.cache_settings.account_ttl_seconds,
                )
        return resolved

    async def create(self, account: Account, *, credential: str) -> Account:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        saved = await self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret),
        )
        self.invalidate(saved)
        self.publish("account.created", public_account(saved))
        return saved

    async def update(
        self,
        account: Account,
        *,
        credential: str = "",
        expected_updated_at: datetime | None = None,
    ) -> Account:
        previous = await self.repository.get(
            account.id, provider=account.provider, enabled_only=False
        )
        account = replace(account, updated_at=datetime.now(UTC))
        secret = credential.strip()
        saved = await self.repository.save(
            account,
            encrypted_credential=self.cipher.encrypt(secret) if secret else None,
            expected_updated_at=expected_updated_at,
        )
        self.invalidate(previous)
        self.invalidate(saved)
        self.publish("account.updated", public_account(saved))
        return saved

    async def set_credential(self, account_id: str, credential: str, *, provider: Provider) -> None:
        secret = credential.strip()
        if not secret:
            raise ValueError("credential is required")
        account = await self.repository.get(account_id, provider=provider, enabled_only=False)
        await self.repository.set_credential(
            account_id,
            self.cipher.encrypt(secret),
            provider=provider,
        )
        updated = await self.repository.get(account_id, provider=provider, enabled_only=False)
        self.invalidate(account)
        self.invalidate(updated)
        self.publish("account.updated", public_account(updated))

    async def delete(self, account_id: str, *, provider: Provider) -> None:
        account = await self.repository.get(account_id, provider=provider, enabled_only=False)
        await self.repository.delete(account_id, provider=provider)
        self.invalidate(account)
        self.publish("account.deleted", AccountIdentity(account.id, account.provider.value))

    async def verify(self, selector: str, *, provider: Provider) -> ConnectionVerification:
        account = await self.repository.get(selector, provider=provider)
        credential = self.cipher.decrypt(
            await self.repository.credential(account.id, provider=provider)
        )
        result = await asyncio.to_thread(self.verifier.verify, account, credential)
        self.publish(
            "account.verified",
            AccountVerified(account.id, account.provider.value, result.ok is True),
        )
        return result

    async def verify_candidate(
        self,
        account: Account,
        *,
        credential: str = "",
        credential_account_id: str = "",
    ) -> ConnectionVerification:
        secret = credential.strip()
        if not secret:
            selector = credential_account_id.strip()
            if not selector:
                raise ValueError("credential is required for a new account")
            existing = await self.repository.get(
                selector, provider=account.provider, enabled_only=False
            )
            secret = self.cipher.decrypt(
                await self.repository.credential(existing.id, provider=account.provider)
            )
        return await asyncio.to_thread(self.verifier.verify, account, secret)


class InvocationAuditService:
    def __init__(
        self,
        repository: InvocationRepository,
        config: AdminConfigService | None = None,
        publisher: RealtimePublisher | None = None,
    ) -> None:
        self.repository = repository
        self.config = config
        self.publisher = publisher

    async def record(self, invocation: Invocation) -> None:
        await self.record_many([invocation])

    async def record_many(self, invocations: Sequence[Invocation]) -> None:
        if not invocations:
            return
        capture_payloads = True
        if self.config is not None:
            config = await self.config.get()
            if not config.logging_enabled:
                return
            capture_payloads = config.logging_capture_payloads
        await self.repository.append_many(invocations, capture_payloads=capture_payloads)
        if self.publisher is not None:
            events = tuple(item.captured(capture_payloads) for item in invocations)
            self.publisher(
                "mcp.calls",
                "batch",
                InvocationBatch(events=events, count=len(events)),
            )

    async def recent(self, *, limit: int = 100) -> Sequence[Invocation]:
        return await self.repository.recent(limit=limit)

    async def query(self, query: InvocationQuery) -> InvocationPage:
        return await self.repository.query(query)

    async def clear(self) -> int:
        return await self.repository.clear()

    async def delete(self, invocation_id: str) -> bool:
        return await self.repository.delete(invocation_id)

    async def summary(self) -> InvocationSummary:
        return await self.repository.summary()

    async def cleanup(self) -> int:
        return await self.repository.cleanup()


class OAuthSessionService(_RepositoryBinding[OAuthSessionRepository]):
    async def record(self, event: OAuthSessionEvent) -> OAuthSession:
        return await self.repository.apply_event(event)

    async def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]:
        return await self.repository.recent(limit=limit)


class SnapshotService(_RepositoryBinding[SnapshotRepository]):
    async def ensure(
        self,
        key: str,
        *,
        category: SnapshotCategory,
        coverage: CoverageRequest | None = None,
        refresh_after_seconds: int,
    ) -> AdminSnapshot:
        return await self.repository.ensure(
            key,
            category=category,
            coverage=coverage,
            refresh_after_seconds=refresh_after_seconds,
        )

    async def get(self, key: str) -> AdminSnapshot | None:
        return await self.repository.get(key)

    async def list_category(
        self,
        category: SnapshotCategory,
        *,
        limit: int = 1000,
    ) -> Sequence[AdminSnapshot]:
        return await self.repository.list_category(category, limit=limit)

    async def due(
        self,
        category: SnapshotCategory,
        *,
        retry_after_seconds: int = 30,
        limit: int = 100,
    ) -> list[AdminSnapshot]:
        now = datetime.now(UTC)
        snapshots = await self.repository.list_category(category, limit=limit)
        return [
            snapshot
            for snapshot in snapshots
            if snapshot.due(now, retry_after_seconds=retry_after_seconds)
        ]

    async def mark_attempt(self, key: str) -> None:
        await self.repository.mark_attempt(key)

    async def store_success(
        self,
        key: str,
        content: SnapshotContent,
    ) -> AdminSnapshot:
        return await self.repository.store_success(key, content)

    async def store_error(self, key: str, exc: Exception) -> AdminSnapshot:
        return await self.repository.store_error(key, exc)


class AdminConfigService:
    def __init__(
        self,
        repository: AdminConfigRepository,
        *,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.repository = repository
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None

    async def get(self) -> AdminConfig:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.admin_config(), AdminConfigDocument)
            if cached is not None:
                return cached.record()
        result = await self.repository.get()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.admin_config(),
                AdminConfigDocument.from_record(result),
                ttl_seconds=self.cache_settings.admin_config_ttl_seconds,
            )
        return result

    async def update(self, config: AdminConfig) -> AdminConfig:
        result = await self.repository.save(config)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.admin_config(),
                AdminConfigDocument.from_record(result),
                ttl_seconds=self.cache_settings.admin_config_ttl_seconds,
            )
        return result


class RuntimeSettingsService:
    def __init__(
        self,
        repository: RuntimeSettingsRepository,
        *,
        cipher: CredentialCipher | None = None,
        cache: CacheBackend | None = None,
        cache_settings: ValkeySettings | None = None,
    ) -> None:
        self.repository = repository
        self.cipher = cipher
        self.cache = cache
        self.cache_settings = cache_settings or ValkeySettings()
        self.cache_keys = CacheKeys(cache) if cache is not None else None

    async def terminal_policy(self) -> TerminalRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.terminal_policy(), TerminalRuntimePolicy)
            if cached is not None:
                return cached
        result = await self.repository.get_terminal_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.terminal_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy:
        result = await self.repository.save_terminal_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.terminal_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def mcp_policy(self) -> McpRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.mcp_policy(), McpRuntimePolicy)
            if cached is not None:
                return cached
        result = await self.repository.get_mcp_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.mcp_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy:
        result = await self.repository.save_mcp_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.mcp_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def github_policy(self) -> GitHubRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.github_policy(), GitHubRuntimePolicy)
            if cached is not None:
                return cached
        result = await self.repository.get_github_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.github_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy:
        result = await self.repository.save_github_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.github_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def gitlab_policy(self) -> GitLabRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.gitlab_policy(), GitLabRuntimePolicy)
            if cached is not None:
                return cached
        result = await self.repository.get_gitlab_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.gitlab_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_gitlab_policy(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy:
        result = await self.repository.save_gitlab_policy(policy)
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.gitlab_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def browser_policy(self) -> BrowserRuntimePolicy:
        if self.cache is not None and self.cache_keys is not None:
            cached = self.cache.get_model(self.cache_keys.browser_policy(), BrowserRuntimePolicy)
            if cached is not None:
                return cached
        result = await self.repository.get_browser_policy()
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.browser_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def update_browser_policy(
        self,
        policy: BrowserRuntimePolicy,
        *,
        extension_token: str | None = None,
        clear_extension_token: bool = False,
    ) -> BrowserRuntimePolicy:
        encrypted: str | None = None
        if extension_token is not None and extension_token.strip():
            if self.cipher is None:
                raise RuntimeError("browser runtime credential cipher is unavailable")
            encrypted = self.cipher.encrypt(extension_token.strip())
        result = await self.repository.save_browser_policy(
            policy,
            encrypted_extension_token=encrypted,
            clear_extension_token=clear_extension_token,
        )
        if self.cache is not None and self.cache_keys is not None:
            self.cache.set_model(
                self.cache_keys.browser_policy(),
                result,
                ttl_seconds=self.cache_settings.policy_ttl_seconds,
            )
        return result

    async def browser_launcher_policy(self) -> BrowserLauncherPolicy:
        policy = await self.browser_policy()
        ciphertext = await self.repository.browser_extension_token()
        token = ""
        if ciphertext:
            if self.cipher is None:
                raise RuntimeError("browser runtime credential cipher is unavailable")
            token = self.cipher.decrypt(ciphertext)
        return BrowserLauncherPolicy(
            external_enabled=policy.external_enabled,
            external_mcp_url=policy.external_mcp_url,
            call_timeout_seconds=policy.call_timeout_seconds,
            auto_disconnect_enabled=policy.auto_disconnect_enabled,
            idle_timeout_seconds=policy.idle_timeout_seconds,
            profile_dir_name=policy.profile_dir_name,
            extension_token_configured=policy.extension_token_configured,
            extension_token=token,
        )
