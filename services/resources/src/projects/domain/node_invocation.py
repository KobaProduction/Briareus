"""Select exactly one current project account; tool existence is a Hand authority."""

from dataclasses import dataclass
from typing import Literal, NamedTuple
from uuid import UUID

from projects.domain.provider_connections import ConnectionFailure

type ProviderModule = Literal["svc", "infrastructure"]
type SourceProvider = Literal["github", "gitlab"]

type InfrastructureProvider = Literal["signoz", "coolify"]
type InvocationProvider = SourceProvider | InfrastructureProvider


@dataclass(frozen=True, slots=True)
class SourceCustody:
    target: SourceProvider
    account_required: bool

    def __post_init__(self) -> None:
        if self.target not in {"github", "gitlab"}:
            raise ValueError("Explicit Source Control target required")


@dataclass(frozen=True, slots=True)
class ProviderCall:
    """Only account custody selectors; arbitrary tool input belongs to the Hand."""

    tool: str
    account: str | None = None
    provider: InfrastructureProvider | None = None
    source: SourceCustody | None = None


class ProviderSelection(NamedTuple):
    provider: InvocationProvider | None
    account: str | None


class ProviderRequirement(NamedTuple):
    provider: InvocationProvider | None
    account_required: bool
    provider_argument: Literal["unused", "optional", "required"] = "unused"


@dataclass(frozen=True)
class AccountProvenance:
    project_uuid: UUID | None
    team_uuid: UUID | None
    deleted: bool
    provider: str


def require_current_accounts(
    accounts: tuple[AccountProvenance, ...],
    project_uuid: UUID,
    providers: frozenset[str],
    *,
    selected: bool,
) -> None:
    if len(accounts) > 64 or (selected and len(accounts) != 1):
        raise ConnectionFailure(403, "Current project account unavailable")
    if any(
        account.project_uuid != project_uuid
        or account.team_uuid is not None
        or account.deleted
        or account.provider not in providers
        for account in accounts
    ):
        raise ConnectionFailure(403, "Current project account ownership mismatch")


def select_provider(module: ProviderModule, call: ProviderCall) -> ProviderSelection:
    if module == "svc" and call.tool in {"source_control", "source_control_capabilities"}:
        if call.source is None or call.provider is not None:
            raise ValueError("Closed Source Control custody required")
        account = account_selector(call.account) if call.source.account_required else None
        if not call.source.account_required and call.account is not None:
            raise ValueError("Source account catalogue does not select an account")
        return ProviderSelection(call.source.target, account)
    if call.source is not None:
        raise ValueError("Unexpected Source Control target")
    required = provider_requirement(module, call.tool)
    if required.provider_argument == "required" and call.provider is None:
        raise ValueError("Explicit infrastructure provider required")
    provider = call.provider if required.provider_argument != "unused" else required.provider
    account = account_selector(call.account) if required.account_required else None
    return ProviderSelection(provider, account)


def provider_requirement(module: ProviderModule, tool: str) -> ProviderRequirement:
    if module not in {"svc", "infrastructure"}:
        raise ValueError("Private provider module required")
    if module == "svc":
        if tool in {"source_control", "source_control_capabilities"}:
            raise ValueError("Explicit Source Control custody required")
        if tool in {"github_accounts", "accounts"}:
            return ProviderRequirement("github" if tool == "github_accounts" else "gitlab", False)
        return ProviderRequirement("github" if tool.startswith("github_") else "gitlab", True)
    if tool == "observability_sources":
        return ProviderRequirement(None, False, "optional")
    if tool == "observability_connection":
        return ProviderRequirement(None, True, "required")
    return ProviderRequirement(infrastructure_provider(tool), True)


def account_selector(selector: str | None) -> str:
    if selector is None or not 0 < len(selector) <= 128 or selector.strip() != selector:
        raise ValueError("One explicit project account selector required")
    return selector


def original_tool(module: ProviderModule, value: str) -> str:
    if value.startswith(module + "_operation_"):
        raise ValueError("Original provider tool required")
    return value


def infrastructure_provider(tool: str) -> InfrastructureProvider:
    if tool in {
        "observability_search_logs",
        "observability_search_traces",
        "observability_query_telemetry",
        "observability_list_services",
        "observability_field_keys",
        "observability_field_values",
    }:
        return "signoz"
    return "coolify"
