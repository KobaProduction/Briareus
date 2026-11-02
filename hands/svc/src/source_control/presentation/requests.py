"""Select a provider before validating its operation-specific parameter schema."""

from typing import Annotated, Literal

from mcp.types import CallToolRequestParams
from pydantic import BaseModel, ConfigDict, Field

from .contracts import SourceCapabilities, SourceCapability, SourceTarget
from .github import GITHUB_COMMANDS, GitHubCommand, GitHubListAccounts
from .gitlab import GITLAB_COMMANDS, GitLabCommand, GitLabListAccounts


class GitHubRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    target: Literal["github"]
    command: GitHubCommand


class GitLabRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    target: Literal["gitlab"]
    command: GitLabCommand


type SourceRequest = Annotated[GitHubRequest | GitLabRequest, Field(discriminator="target")]


def require_source_account(request: SourceRequest, account_id: str | None) -> None:
    # Keep the selected account at the MCP/continuation boundary. Only account
    # listing has no selected account in either original provider contract.
    listing = isinstance(request.command, (GitHubListAccounts, GitLabListAccounts))
    if listing and account_id is not None:
        raise ValueError("Account listing does not select an account")
    if not listing and account_id is None:
        raise ValueError("Selected account required")


def legacy_call(request: SourceRequest, account_id: str | None) -> CallToolRequestParams:
    require_source_account(request, account_id)
    # This is the existing SDK wire input, never an application result contract.
    arguments = request.command.model_dump(exclude={"operation"}, exclude_unset=True)
    if account_id is not None:
        arguments["account_id"] = account_id
    return CallToolRequestParams(name=request.command.tool_name, arguments=arguments)


def capabilities(target: SourceTarget) -> SourceCapabilities:
    if target == "github":
        commands = GITHUB_COMMANDS
    elif target == "gitlab":
        commands = GITLAB_COMMANDS
    else:
        raise ValueError("Unknown Source Control target")
    return SourceCapabilities(
        target=target,
        operations=tuple(
            SourceCapability(operation=command.operation_name, provider_tool=command.tool_name)
            for command in commands
        ),
    )
