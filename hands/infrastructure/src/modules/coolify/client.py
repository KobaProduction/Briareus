"""Compatibility exports for the shared provider implementation."""

import http as http
import ssl as ssl
import urllib as urllib

from pydantic import BaseModel as BaseModel

from common.account_contracts import ResolvedAccount as ResolvedAccount
from common.http_transport import HttpTransportError as HttpTransportError
from common.http_transport import PooledHttpTransport as PooledHttpTransport
from infrastructure_runtime.providers.coolify.client import CoolifyClient as CoolifyClient
from infrastructure_runtime.providers.coolify.client import CoolifyClientError as CoolifyClientError

from .metadata_views import ApplicationDeployments as ApplicationDeployments
from .metadata_views import ApplicationList as ApplicationList
from .metadata_views import ApplicationMetadata as ApplicationMetadata
from .metadata_views import ApplicationStorages as ApplicationStorages
from .metadata_views import ApplicationVariables as ApplicationVariables
from .metadata_views import CoolifyAccountSummary as CoolifyAccountSummary
from .metadata_views import DeploymentInventory as DeploymentInventory
from .metadata_views import DeploymentList as DeploymentList
from .metadata_views import DeploymentMetadata as DeploymentMetadata
from .metadata_views import EnvironmentList as EnvironmentList
from .metadata_views import ServerList as ServerList
from .metadata_views import ServerResourceList as ServerResourceList
from .metadata_views import StorageInventory as StorageInventory
from .metadata_views import StorageMetadata as StorageMetadata
from .metadata_views import TeamMetadata as TeamMetadata
