from typing import Annotated

from pydantic import Field
from pydantic_settings import NoDecode

from service_runtime.owner_settings import _DEFAULT_PUBLIC_HOSTS as _DEFAULT_PUBLIC_HOSTS
from service_runtime.owner_settings import _DEFAULT_PUBLIC_ORIGINS as _DEFAULT_PUBLIC_ORIGINS
from service_runtime.owner_settings import AdminApiSettings as AdminApiSettings
from service_runtime.owner_settings import AnalysisSettings as AnalysisSettings
from service_runtime.owner_settings import (
    AuthorizationAccessClientSettings as AuthorizationAccessClientSettings,
)
from service_runtime.owner_settings import (
    AuthorizationServiceSettings as AuthorizationServiceSettings,
)
from service_runtime.owner_settings import BridgeSettings as BridgeSettings
from service_runtime.owner_settings import BrowserSettings as BrowserSettings
from service_runtime.owner_settings import FileSettings as FileSettings
from service_runtime.owner_settings import (
    GatewayAuthorizationSettings as GatewayAuthorizationSettings,
)
from service_runtime.owner_settings import GhidraSettings as GhidraSettings
from service_runtime.owner_settings import GitHubPolicySettings as _GitHubPolicySettings
from service_runtime.owner_settings import GitLabSettings as GitLabSettings
from service_runtime.owner_settings import TerminalSettings as TerminalSettings
from service_runtime.settings import AdminApiClientSettings as AdminApiClientSettings
from service_runtime.settings import AsgiServerSettings as AsgiServerSettings
from service_runtime.settings import FrozenSettings as FrozenSettings
from service_runtime.settings import HttpSurfaceSettings as HttpSurfaceSettings
from service_runtime.settings import ObservabilitySettings as ObservabilitySettings
from service_runtime.settings import PrivateRuntimeSettings as PrivateRuntimeSettings
from service_runtime.settings import ProcessSettings as ProcessSettings
from service_runtime.settings import ValkeySettings as ValkeySettings
from service_runtime.settings import _csv as _csv
from service_runtime.settings import _frozenset_value as _frozenset_value
from service_runtime.settings import _tuple_value as _tuple_value


class GitHubPolicySettings(_GitHubPolicySettings):
    protected_branches: Annotated[frozenset[str], NoDecode] = Field(
        frozenset(),
        validation_alias="GITHUB_AGENT_PROTECTED_BRANCHES",
    )
