from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from domain.accounts import Account, Provider
from domain.analysis import CoverageRequest
from domain.configuration import AdminConfig
from domain.oauth_sessions import OAuthSession
from domain.snapshots import SnapshotCategory
from domain.telemetry import Invocation, InvocationPage, InvocationQuery, InvocationSummary

from application.snapshot_contracts import AdminSnapshot, SnapshotContent
from common.oauth_session_contracts import OAuthSessionEvent
from common.runtime_policy_contracts import (
    BrowserRuntimePolicy,
    GitHubRuntimePolicy,
    GitLabRuntimePolicy,
    McpRuntimePolicy,
    TerminalRuntimePolicy,
)

from .provider_verification import ConnectionVerification


class AccountRepository(Protocol):
    async def list(
        self,
        *,
        provider: Provider | None = None,
        enabled_only: bool = True,
    ) -> Sequence[Account]: ...

    async def get(
        self,
        selector: str,
        *,
        provider: Provider,
        enabled_only: bool = True,
    ) -> Account: ...

    async def save(
        self,
        account: Account,
        *,
        encrypted_credential: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> Account: ...

    async def delete(self, account_id: str, *, provider: Provider) -> None: ...

    async def set_credential(
        self,
        account_id: str,
        encrypted_value: str,
        *,
        provider: Provider,
    ) -> None: ...

    async def credential(self, account_id: str, *, provider: Provider) -> str: ...


class InvocationRepository(Protocol):
    async def append(self, invocation: Invocation, *, capture_payloads: bool = True) -> None: ...

    async def append_many(
        self,
        invocations: Sequence[Invocation],
        *,
        capture_payloads: bool = True,
    ) -> None: ...

    async def recent(self, *, limit: int = 100) -> Sequence[Invocation]: ...

    async def query(self, query: InvocationQuery) -> InvocationPage: ...

    async def clear(self) -> int: ...

    async def delete(self, invocation_id: str) -> bool: ...

    async def summary(self) -> InvocationSummary: ...

    async def cleanup(self) -> int: ...


class OAuthSessionRepository(Protocol):
    async def apply_event(self, event: OAuthSessionEvent) -> OAuthSession: ...

    async def recent(self, *, limit: int = 200) -> Sequence[OAuthSession]: ...


class SnapshotRepository(Protocol):
    async def ensure(
        self,
        key: str,
        *,
        category: SnapshotCategory,
        coverage: CoverageRequest | None = None,
        refresh_after_seconds: int,
    ) -> AdminSnapshot: ...

    async def get(self, key: str) -> AdminSnapshot | None: ...

    async def list_category(
        self,
        category: SnapshotCategory,
        *,
        limit: int = 1000,
    ) -> Sequence[AdminSnapshot]: ...

    async def mark_attempt(self, key: str, *, status: str = "refreshing") -> None: ...

    async def store_success(
        self,
        key: str,
        content: SnapshotContent,
    ) -> AdminSnapshot: ...

    async def store_error(self, key: str, exc: Exception) -> AdminSnapshot: ...


class AdminConfigRepository(Protocol):
    async def get(self) -> AdminConfig: ...

    async def save(self, config: AdminConfig) -> AdminConfig: ...


class RuntimeSettingsRepository(Protocol):
    async def get_terminal_policy(self) -> TerminalRuntimePolicy: ...

    async def save_terminal_policy(
        self,
        policy: TerminalRuntimePolicy,
    ) -> TerminalRuntimePolicy: ...

    async def get_mcp_policy(self) -> McpRuntimePolicy: ...

    async def save_mcp_policy(self, policy: McpRuntimePolicy) -> McpRuntimePolicy: ...

    async def get_github_policy(self) -> GitHubRuntimePolicy: ...

    async def save_github_policy(self, policy: GitHubRuntimePolicy) -> GitHubRuntimePolicy: ...

    async def get_gitlab_policy(self) -> GitLabRuntimePolicy: ...

    async def save_gitlab_policy(self, policy: GitLabRuntimePolicy) -> GitLabRuntimePolicy: ...

    async def get_browser_policy(self) -> BrowserRuntimePolicy: ...

    async def save_browser_policy(
        self,
        policy: BrowserRuntimePolicy,
        *,
        encrypted_extension_token: str | None = None,
        clear_extension_token: bool = False,
    ) -> BrowserRuntimePolicy: ...

    async def browser_extension_token(self) -> str: ...


class CredentialCipher(Protocol):
    def encrypt(self, plaintext: str) -> str: ...

    def decrypt(self, ciphertext: str) -> str: ...


class ConnectionVerifier(Protocol):
    def verify(self, account: Account, credential: str) -> ConnectionVerification: ...
