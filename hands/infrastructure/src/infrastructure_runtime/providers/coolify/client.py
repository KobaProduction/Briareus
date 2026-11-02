from __future__ import annotations

import http as http
import ssl as ssl
import urllib.parse

from pydantic import BaseModel

from infrastructure_runtime.providers.http_connection import ProviderHttpConnection
from service_runtime.account_contracts import ResolvedAccount as ResolvedAccount
from service_runtime.http_transport import HttpTransportError
from service_runtime.providers.tls import provider_ssl_context as provider_ssl_context

from .metadata_views import (
    ApplicationDeployments,
    ApplicationList,
    ApplicationMetadata,
    ApplicationStorages,
    ApplicationVariables,
    CoolifyAccountSummary,
    DeploymentInventory,
    DeploymentList,
    DeploymentMetadata,
    EnvironmentList,
    ServerList,
    ServerResourceList,
    StorageInventory,
    StorageMetadata,
    TeamMetadata,
)


class CoolifyClientError(RuntimeError):
    pass


class CoolifyClient(ProviderHttpConnection):
    _url_error_type = CoolifyClientError
    _url_error_message = "Coolify base_url must be absolute HTTP(S)"
    _http_span_name = "provider.coolify.http"
    _http_provider = "coolify"

    def _target(self, path: str, query: dict[str, str] | None = None) -> str:
        if not path.startswith("/"):
            raise CoolifyClientError("Coolify path must start with /")
        target = self._base_path + "/api/v1" + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        return target

    def _get[T: BaseModel](
        self, path: str, *, response_type: type[T], query: dict[str, str] | None = None
    ) -> T:
        try:
            response = self._transport.request(
                "GET",
                self._target(path, query),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.account.credential}",
                    "User-Agent": "mcp-bridge-coolify",
                },
                reconnect_retries=1,
            )
        except HttpTransportError as exc:
            raise CoolifyClientError(f"Coolify transport error: {exc}") from exc
        if response.status >= 400:
            raise CoolifyClientError(f"Coolify HTTP {response.status}")
        return response_type.model_validate_json(response.body)

    def current_team(self) -> TeamMetadata:
        return self._get("/teams/current", response_type=TeamMetadata)

    def servers(self) -> ServerList:
        return self._get("/servers", response_type=ServerList)

    def server_resources(self, uuid: str) -> ServerResourceList:
        return self._get(
            "/servers/" + urllib.parse.quote(uuid, safe="") + "/resources",
            response_type=ServerResourceList,
        )

    def applications(self) -> ApplicationList:
        return self._get("/applications", response_type=ApplicationList)

    def application(self, uuid: str) -> ApplicationMetadata:
        return self._get(
            "/applications/" + urllib.parse.quote(uuid, safe=""), response_type=ApplicationMetadata
        )

    def application_storages(self, uuid: str) -> ApplicationStorages:
        """Return safe persistent/file storage metadata without file contents or host paths."""
        inventory = self._get(
            "/applications/" + urllib.parse.quote(uuid, safe="") + "/storages",
            response_type=StorageInventory,
        )
        persistent = [
            StorageMetadata.from_details(row, "persistent") for row in inventory.persistent_storages
        ]
        files = [StorageMetadata.from_details(row, "file") for row in inventory.file_storages]
        return ApplicationStorages(
            application_uuid=uuid,
            persistent_storages=persistent,
            file_storages=files,
            count=len(persistent) + len(files),
            contents_exposed=False,
            host_paths_exposed=False,
        )

    def application_variables(self, uuid: str) -> ApplicationVariables:
        """Return environment-variable metadata without exposing any values."""
        inventory = self._get(
            "/applications/" + urllib.parse.quote(uuid, safe="") + "/envs",
            response_type=EnvironmentList,
        )
        variables = inventory.root
        variables.sort(key=lambda item: str(item.key or "").casefold())
        return ApplicationVariables(
            application_uuid=uuid, variables=variables, count=len(variables), values_exposed=False
        )

    def deployments(self) -> DeploymentList:
        return self._get("/deployments", response_type=DeploymentList)

    def deployment(self, uuid: str) -> DeploymentMetadata:
        return self._get(
            "/deployments/" + urllib.parse.quote(uuid, safe=""), response_type=DeploymentMetadata
        )

    def application_deployments(self, uuid: str) -> ApplicationDeployments:
        inventory = self._get(
            "/deployments/applications/" + urllib.parse.quote(uuid, safe=""),
            response_type=DeploymentInventory,
        )
        return ApplicationDeployments(
            deployments=inventory.deployments, count=len(inventory.deployments)
        )

    def account_summary(self) -> CoolifyAccountSummary:
        return CoolifyAccountSummary(
            id=self.account.id,
            alias=self.account.alias,
            provider=self.account.provider,
            auth_type=self.account.auth_type,
            base_url=self.account.base_url,
            external_id=self.account.external_id,
            verify_tls=self.account.verify_tls,
            ca_cert_pem=self.account.ca_cert_pem,
            enabled=self.account.enabled,
            created_at=self.account.created_at,
            updated_at=self.account.updated_at,
            credential_configured=True,
            permission_contract="read-only; strict safe-field projection",
        )
