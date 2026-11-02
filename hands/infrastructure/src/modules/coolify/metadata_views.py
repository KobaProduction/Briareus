"""Compatibility exports for the shared provider implementation."""

from typing import Literal as Literal

from pydantic import BaseModel as BaseModel
from pydantic import RootModel as RootModel

from common.account_contracts import AccountConnectionSummary as AccountConnectionSummary
from common.provider_identity import CoolifyTeamMetadata as CoolifyTeamMetadata
from infrastructure_runtime.providers.coolify.metadata_views import (
    ApplicationDeployments as ApplicationDeployments,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    ApplicationList as ApplicationList,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    ApplicationMetadata as ApplicationMetadata,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    ApplicationStorages as ApplicationStorages,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    ApplicationVariables as ApplicationVariables,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    CoolifyAccountSummary as CoolifyAccountSummary,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    DeploymentInventory as DeploymentInventory,
)
from infrastructure_runtime.providers.coolify.metadata_views import DeploymentList as DeploymentList
from infrastructure_runtime.providers.coolify.metadata_views import (
    DeploymentMetadata as DeploymentMetadata,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    EnvironmentList as EnvironmentList,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    EnvironmentMetadata as EnvironmentMetadata,
)
from infrastructure_runtime.providers.coolify.metadata_views import ServerList as ServerList
from infrastructure_runtime.providers.coolify.metadata_views import ServerMetadata as ServerMetadata
from infrastructure_runtime.providers.coolify.metadata_views import (
    ServerResourceList as ServerResourceList,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    ServerResourceMetadata as ServerResourceMetadata,
)
from infrastructure_runtime.providers.coolify.metadata_views import StorageDetails as StorageDetails
from infrastructure_runtime.providers.coolify.metadata_views import (
    StorageInventory as StorageInventory,
)
from infrastructure_runtime.providers.coolify.metadata_views import (
    StorageMetadata as StorageMetadata,
)
from infrastructure_runtime.providers.coolify.metadata_views import TeamMetadata as TeamMetadata
