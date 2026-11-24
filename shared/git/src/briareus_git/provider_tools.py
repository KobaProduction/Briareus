"""Shared MCP registrations for semantically identical provider capabilities.

Native-only schemas are kept in provider Hands. Shared protocols are structural:
a provider supplies its own API client, not an extra forwarding service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .files import FileEncoding, RepositoryFileProvider


class RepositoryRefsProvider(Protocol):
    def get_commit(self, repository: str, ref: str, /) -> JsonObject: ...
    def create_branch(self, repository: str, branch: str, from_branch: str, /) -> JsonObject: ...
    def delete_branch(self, repository: str, branch: str, /) -> JsonObject: ...


class IssueProvider(Protocol):
    def get_issue(self, repository: str, number: int, /) -> JsonObject: ...
    def create_issue(
        self, repository: str, title: str, body: str, labels: list[str] | None, /
    ) -> JsonObject: ...
    def update_issue(
        self,
        repository: str,
        number: int,
        title: str | None,
        body: str | None,
        state: str | None,
        labels: list[str] | None,
        /,
    ) -> JsonObject: ...


class CheckoutProvider(Protocol):
    def checkout_repository(
        self,
        repository: str,
        destination: str,
        /,
        *,
        mode: str,
        ref: str,
        overwrite: bool,
    ) -> JsonObject: ...

    def authorize_local_git(
        self,
        repository: str,
        destination: str,
        /,
        *,
        remote: str,
    ) -> JsonObject: ...


def register_account_tools(
    mcp: FastMCP[None],
    list_accounts: Callable[[], JsonObject],
    account_capabilities_factory: Callable[[str, str], JsonObject],
    read_annotations: ToolAnnotations,
    provider: str,
) -> None:
    @mcp.tool(title=f"{provider} accounts", annotations=read_annotations)
    def accounts() -> JsonObject:
        """List configured accounts and potential capabilities without credentials."""
        return list_accounts()

    @mcp.tool(title=f"{provider} account capabilities", annotations=read_annotations)
    def account_capabilities(account_id: str, repository: str = "") -> JsonObject:
        """Inspect account permissions and optionally effective repository/project rights."""
        return account_capabilities_factory(account_id, repository)


def register_file_read(
    mcp: FastMCP[None],
    client_factory: Callable[[str], RepositoryFileProvider],
    read_annotations: ToolAnnotations,
    provider: str,
) -> None:
    @mcp.tool(title=f"{provider} get file", annotations=read_annotations)
    def get_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
        encoding: FileEncoding = "utf-8",
    ) -> JsonObject:
        """Read a file at an optional ref (default: the provider's default branch).

        UTF-8 returns content (invalid bytes are replaced); base64 returns
        content_base64 without losing binary data.
        """
        return client_factory(account_id).get_file(repository, path, ref, encoding)


def register_ref_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], RepositoryRefsProvider],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    provider: str,
) -> None:
    @mcp.tool(title=f"{provider} get commit", annotations=read_annotations)
    def get_commit(account_id: str, repository: str, ref: str) -> JsonObject:
        """Read one commit including changed-file information when available."""
        return client_factory(account_id).get_commit(repository, ref)

    @mcp.tool(title=f"{provider} create branch", annotations=write_annotations)
    def create_branch(
        account_id: str,
        repository: str,
        branch: str,
        from_branch: str = "main",
    ) -> JsonObject:
        """Create a non-protected working branch from an existing branch or ref."""
        return client_factory(account_id).create_branch(repository, branch, from_branch)

    @mcp.tool(title=f"{provider} delete branch", annotations=destructive_annotations)
    def delete_branch(account_id: str, repository: str, branch: str) -> JsonObject:
        """Delete a non-protected branch."""
        return client_factory(account_id).delete_branch(repository, branch)


def register_issue_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], IssueProvider],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    provider: str,
) -> None:
    @mcp.tool(title=f"{provider} get issue", annotations=read_annotations)
    def get_issue(account_id: str, repository: str, number: int) -> JsonObject:
        """Read one issue by its repository/project-local number."""
        return client_factory(account_id).get_issue(repository, number)

    @mcp.tool(title=f"{provider} create issue", annotations=write_annotations)
    def create_issue(
        account_id: str,
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Create an issue with an optional body and labels."""
        return client_factory(account_id).create_issue(repository, title, body, labels)

    @mcp.tool(title=f"{provider} update issue", annotations=write_annotations)
    def update_issue(
        account_id: str,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> JsonObject:
        """Update an issue; state is open or closed."""
        return client_factory(account_id).update_issue(
            repository, number, title, body, state, labels
        )


def register_checkout_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], CheckoutProvider],
    write_annotations: ToolAnnotations,
    provider: str,
    transport_enabled: Callable[[], bool],
) -> None:
    @mcp.tool(title=f"{provider} checkout repository", annotations=write_annotations)
    def checkout_repository(
        account_id: str,
        repository: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        """Checkout into the shared workspace.

        mode='snapshot' creates a shallow working tree without .git; mode='git'
        keeps Git metadata and history. Reuse an existing canonical checkout
        after verifying its remote. destination MUST be relative to SERVER_MOUNT_PATH,
        e.g. projects/heating-station, not /workspace/projects/heating-station.
        For Terminal Git authentication use authorize_local_git with the same
        account, repository and returned path. Checkout alone does not persist auth.
        """
        return client_factory(account_id).checkout_repository(
            repository, destination, mode=mode, ref=ref, overwrite=overwrite
        )

    @mcp.tool(title="Authorize Server terminal Git fetch/pull/push", annotations=write_annotations)
    def authorize_local_git(
        account_id: str,
        repository: str,
        destination: str,
        remote: str = "origin",
    ) -> JsonObject:
        """Connect the selected provider account to an existing local Git checkout.

        Use after missing/expired Terminal Git credentials. Inspect accounts and
        select the authorized identity; repository identifies the provider resource,
        destination is the exact mount-relative checkout path, never a workspace ID
        or absolute cwd. Configure credentials and reserved-branch guard without
        fetching, pushing or resetting. Never disclose credentials or switch accounts.
        """
        if not transport_enabled():
            raise RuntimeError("local Git transport is disabled in application settings")
        return client_factory(account_id).authorize_local_git(
            repository, destination, remote=remote
        )
