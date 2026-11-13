from __future__ import annotations

from typing import Annotated

from briareus_environment_parsing import parse_csv_frozenset, parse_csv_tuple
from briareus_server_mount import ServerMountSettings
from pydantic import Field, field_validator
from pydantic_settings import NoDecode


class GitHubPolicySettings(ServerMountSettings):
    public_reader_account: str = Field(
        "",
        validation_alias="GITHUB_PUBLIC_READER_ACCOUNT",
    )
    public_allow_anonymous_fallback: bool = Field(
        True,
        validation_alias="GITHUB_PUBLIC_ALLOW_ANONYMOUS_FALLBACK",
    )
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset(),
        validation_alias="GITHUB_AGENT_PROTECTED_BRANCHES",
    )
    required_checks: Annotated[tuple[str, ...], NoDecode] = Field(
        ("test", "docker"),
        validation_alias="GITHUB_AGENT_REQUIRED_CHECKS",
    )
    required_reviewers: Annotated[tuple[str, ...], NoDecode] = Field(
        (),
        validation_alias="GITHUB_AGENT_REQUIRED_REVIEWERS",
    )

    @field_validator("public_reader_account", mode="before")
    @classmethod
    def _strip_public_reader_account(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("protected_branches", mode="before")
    @classmethod
    def _parse_branches(cls, value: object) -> object:
        return parse_csv_frozenset(value)

    @field_validator("required_checks", mode="before")
    @classmethod
    def _parse_checks(cls, value: object) -> object:
        return parse_csv_tuple(value)

    @field_validator("required_reviewers", mode="before")
    @classmethod
    def _parse_reviewers(cls, value: object) -> object:
        parsed = parse_csv_tuple(value)
        if isinstance(parsed, tuple):
            return tuple(item.casefold() for item in parsed)
        return parsed
