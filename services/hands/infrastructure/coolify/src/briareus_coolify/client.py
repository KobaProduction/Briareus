from __future__ import annotations

import http.client
import ssl
import urllib.parse
from typing import Literal

from briareus_account_contracts import ResolvedAccount
from briareus_http_transport.http_transport import HttpTransportError, PooledHttpTransport
from briareus_json_values import JsonObject, JsonValue, json_loads, json_object, json_object_list

from briareus_coolify.deployment_logs import (
    deployment_log_page,
    runtime_log_page,
    validate_log_window,
)
from briareus_coolify.variable_access import (
    VariableReadConfirmation,
    app_variable_value,
    safe_shared_variable,
    variable_summary,
)


class CoolifyClientError(RuntimeError):
    pass


type CoolifyRequiredPermission = Literal["read", "read:sensitive", "deploy"]

_PERMISSION_GUIDE = (
    "Check Coolify > Keys & Tokens > API Tokens > Edit > Permissions and Access. "
    "Also verify the token owner's role, team, resource scope and API IP allowlist. "
    "Do not enable root/write/delete to fix a read or deploy permission failure."
)


def _permission_error(permission: CoolifyRequiredPermission) -> CoolifyClientError:
    return CoolifyClientError(
        f"Coolify HTTP 403 Forbidden: required API token permission '{permission}' "
        "for this operation, plus access to the selected resource. "
        "The token may lack that permission or may be blocked by its resource "
        f"scope or owner restrictions. {_PERMISSION_GUIDE}"
    )


_APPLICATION_FIELDS = (
    "uuid",
    "name",
    "description",
    "status",
    "container_present",
    "server_status",
    "git_repository",
    "git_branch",
    "git_commit_sha",
    "build_pack",
    "dockerfile_location",
    "docker_compose_location",
    "base_directory",
    "environment_id",
    "destination_id",
    "source_id",
    "compose_parsing_version",
    "is_raw_compose_deployment_enabled",
    "include_source_commit_in_build",
    "inject_build_args_to_dockerfile",
    "disable_build_cache",
    "is_git_shallow_clone_enabled",
    "is_git_submodules_enabled",
    "is_git_lfs_enabled",
    "watch_paths",
    "ports_exposes",
    "fqdn",
    "restart_count",
    "restart_limit_reached",
    "last_online_at",
    "last_restart_at",
    "last_restart_type",
    "created_at",
    "updated_at",
)

_DEPLOYMENT_FIELDS = (
    "id",
    "deployment_uuid",
    "application_id",
    "application_name",
    "server_id",
    "server_name",
    "status",
    "commit",
    "commit_message",
    "force_rebuild",
    "restart_only",
    "rollback",
    "pull_request_id",
    "is_api",
    "is_webhook",
    "created_at",
    "updated_at",
    "finished_at",
)

_TEAM_FIELDS = ("id", "name", "description", "personal_team", "created_at", "updated_at")

_SERVER_FIELDS = (
    "uuid",
    "name",
    "description",
    "proxy_type",
    "server_role",
    "unreachable_count",
    "created_at",
    "updated_at",
)

_SERVER_RESOURCE_FIELDS = (
    "uuid",
    "name",
    "type",
    "status",
    "created_at",
    "updated_at",
)

_SERVICE_FIELDS = (
    "uuid",
    "name",
    "description",
    "status",
    "environment_id",
    "destination_id",
    "service_type",
    "created_at",
    "updated_at",
)

_SERVICE_COMPONENT_FIELDS = ("uuid", "name", "status", "type")


_STORAGE_FIELDS = (
    "uuid",
    "name",
    "mount_path",
    "is_directory",
    "created_at",
    "updated_at",
)


_ENVIRONMENT_METADATA_FIELDS = (
    "uuid",
    "key",
    "is_preview",
    "is_runtime",
    "is_buildtime",
    "is_shared",
    "is_shown_once",
    "is_locked",
    "is_literal",
    "is_multiline",
    "version",
    "created_at",
    "updated_at",
)


def _project(payload: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    return {key: payload.get(key) for key in fields if key in payload}


class CoolifyClient:
    def __init__(self, account: ResolvedAccount, *, timeout_seconds: float = 30.0) -> None:
        self.account = account
        self.base_url = account.base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CoolifyClientError("Coolify base_url must be absolute HTTP(S)")
        self._scheme = parsed.scheme
        self._hostname = parsed.hostname
        self._port = parsed.port
        self._base_path = parsed.path.rstrip("/")
        self._read_confirmations = VariableReadConfirmation()
        self._transport = PooledHttpTransport(
            self._new_connection,
            max_connections=4,
            acquire_timeout=self.timeout_seconds,
            span_name="provider.coolify.http",
            provider="coolify",
        )

    def _context(self) -> ssl.SSLContext | None:
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https":
            return None
        if not self.account.verify_tls:
            return ssl._create_unverified_context()
        if self.account.ca_cert_pem:
            return ssl.create_default_context(cadata=self.account.ca_cert_pem.replace("\\n", "\n"))
        return ssl.create_default_context()

    def _new_connection(self) -> http.client.HTTPConnection:
        if self._scheme == "https":
            return http.client.HTTPSConnection(
                self._hostname,
                self._port,
                timeout=self.timeout_seconds,
                context=self._context(),
            )
        return http.client.HTTPConnection(
            self._hostname,
            self._port,
            timeout=self.timeout_seconds,
        )

    def _target(self, path: str, query: dict[str, str] | None = None) -> str:
        if not path.startswith("/"):
            raise CoolifyClientError("Coolify path must start with /")
        target = self._base_path + "/api/v1" + path
        if query:
            target += "?" + urllib.parse.urlencode(query)
        return target

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        required_permission: CoolifyRequiredPermission = "read",
    ) -> JsonValue:
        try:
            response = self._transport.request(
                method,
                self._target(path, query),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.account.credential}",
                    "User-Agent": "briareus-coolify",
                },
                # Never repeat a side-effecting request after an uncertain failure.
                reconnect_retries=1 if method == "GET" else 0,
            )
        except HttpTransportError as exc:
            raise CoolifyClientError(f"Coolify transport error: {exc}") from exc
        if response.status == 403:
            raise _permission_error(required_permission)
        if response.status == 401:
            raise CoolifyClientError(
                "Coolify HTTP 401 Unauthorized: the selected API token is invalid, "
                "expired or unavailable; check the configured account and its token."
            )
        if response.status >= 400:
            raise CoolifyClientError(f"Coolify HTTP {response.status}")
        return json_loads(response.body, context="Coolify response")

    def _get(
        self,
        path: str,
        *,
        query: dict[str, str] | None = None,
        required_permission: CoolifyRequiredPermission = "read",
    ) -> JsonValue:
        return self._request(
            "GET", path, query=query, required_permission=required_permission
        )

    def _post(self, path: str, *, query: dict[str, str] | None = None) -> JsonValue:
        return self._request("POST", path, query=query, required_permission="deploy")

    @staticmethod
    def _identifier(value: str, label: str) -> str:
        if not 1 <= len(value) <= 128:
            raise ValueError(f"{label} must be a nonempty identifier up to 128 characters")
        if not all(c.isascii() and (c.isalnum() or c in "-_.") for c in value):
            raise ValueError(f"{label} contains invalid characters")
        return urllib.parse.quote(value, safe="")

    @staticmethod
    def _confirmation(confirmed: bool) -> None:
        if confirmed is not True:
            raise ValueError("This operation requires confirm=True and authorized resource scope")

    def current_team(self) -> JsonObject:
        raw = json_object(self._get("/teams/current"), context="Coolify current team")
        return _project(raw, _TEAM_FIELDS)

    def servers(self) -> JsonValue:
        rows = json_object_list(self._get("/servers"), context="Coolify servers")
        return [_project(row, _SERVER_FIELDS) for row in rows]

    def server_resources(self, uuid: str) -> JsonValue:
        rows = json_object_list(
            self._get("/servers/" + urllib.parse.quote(uuid, safe="") + "/resources"),
            context="Coolify server resources",
        )
        return [_project(row, _SERVER_RESOURCE_FIELDS) for row in rows]

    def applications(self) -> JsonValue:
        rows = json_object_list(self._get("/applications"), context="Coolify applications")
        return [_project(row, _APPLICATION_FIELDS) for row in rows]

    def application(self, uuid: str) -> JsonObject:
        raw = json_object(
            self._get("/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application",
        )
        return _project(raw, _APPLICATION_FIELDS)

    def services(self) -> JsonValue:
        rows = json_object_list(self._get("/services"), context="Coolify services")
        return [_project(row, _SERVICE_FIELDS) for row in rows]

    def service(self, uuid: str) -> JsonObject:
        raw = json_object(
            self._get("/services/" + self._identifier(uuid, "service_uuid")),
            context="Coolify service",
        )
        result = _project(raw, _SERVICE_FIELDS)
        for component in ("applications", "databases"):
            entries = raw.get(component)
            if entries is None:
                continue
            rows = json_object_list(entries, context=f"Coolify service.{component}")
            result[component] = [_project(row, _SERVICE_COMPONENT_FIELDS) for row in rows]
        return result


    def application_storages(self, uuid: str) -> JsonObject:
        """Return safe persistent/file storage metadata without file contents or host paths."""
        envelope = json_object(
            self._get("/applications/" + urllib.parse.quote(uuid, safe="") + "/storages"),
            context="Coolify application storages",
        )
        persistent_rows = json_object_list(
            envelope.get("persistent_storages"),
            context="Coolify application storages.persistent_storages",
        )
        file_rows = json_object_list(
            envelope.get("file_storages"),
            context="Coolify application storages.file_storages",
        )
        persistent: list[JsonValue] = [
            {**_project(row, _STORAGE_FIELDS), "type": "persistent"}
            for row in persistent_rows
        ]
        files: list[JsonValue] = [
            {**_project(row, _STORAGE_FIELDS), "type": "file"} for row in file_rows
        ]
        return {
            "application_uuid": uuid,
            "persistent_storages": persistent,
            "file_storages": files,
            "count": len(persistent) + len(files),
            "contents_exposed": False,
            "host_paths_exposed": False,
        }

    def _application_env_rows(
        self,
        uuid: str,
        *,
        required_permission: CoolifyRequiredPermission = "read",
    ) -> list[JsonObject]:
        return json_object_list(
            self._get(
                "/applications/" + self._identifier(uuid, "application_uuid") + "/envs",
                required_permission=required_permission,
            ),
            context="Coolify application environment variables",
        )

    def application_variables(self, uuid: str) -> JsonObject:
        """Report only metadata and configured/length, never plaintext or masks."""
        rows = self._application_env_rows(uuid)
        variables: list[JsonObject] = [
            {**_project(row, _ENVIRONMENT_METADATA_FIELDS), **variable_summary(row)}
            for row in rows
        ]
        variables.sort(key=lambda item: str(item.get("key") or "").casefold())
        variables_json: list[JsonValue] = list(variables)
        return {
            "application_uuid": uuid,
            "variables": variables_json,
            "count": len(variables),
            "values_exposed": False,
        }

    @staticmethod
    def _reject_extra_scope_ids(scope: str, *values: str) -> None:
        if any(values):
            raise ValueError(f"{scope} scope has unexpected resource identifiers")

    def _shared_variable_path(
        self, scope: str, project_uuid: str, environment_uuid: str, server_uuid: str
    ) -> str:
        if scope == "team":
            self._reject_extra_scope_ids("team", project_uuid, environment_uuid, server_uuid)
            path = "/team/envs"
        elif scope == "project":
            self._reject_extra_scope_ids("project", environment_uuid, server_uuid)
            path = "/projects/" + self._identifier(project_uuid, "project_uuid") + "/envs"
        elif scope == "environment":
            self._reject_extra_scope_ids("environment", server_uuid)
            path = (
                "/projects/" + self._identifier(project_uuid, "project_uuid")
                + "/environments/" + self._identifier(environment_uuid, "environment_uuid")
                + "/envs"
            )
        elif scope == "server":
            self._reject_extra_scope_ids("server", project_uuid, environment_uuid)
            path = "/servers/" + self._identifier(server_uuid, "server_uuid") + "/envs"
        else:
            raise ValueError("scope must be team, project, environment or server")
        return path

    def shared_variables(
        self,
        scope: str,
        *,
        project_uuid: str = "",
        environment_uuid: str = "",
        server_uuid: str = "",
        masked: bool = False,
    ) -> JsonObject:
        """Only the specified shared scope; never return actual shared values."""
        path = self._shared_variable_path(
            scope, project_uuid, environment_uuid, server_uuid
        )
        raw = self._get(path, required_permission="read:sensitive")
        if isinstance(raw, dict):
            raw = raw.get("data", raw.get("variables"))
        rows = json_object_list(raw, context="Coolify shared variables")
        variables = [safe_shared_variable(row, masked=masked) for row in rows]
        variables.sort(key=lambda item: str(item.get("key") or "").casefold())
        return {
            "scope": scope,
            "variables": list(variables),
            "count": len(variables),
            "raw_values_exposed": False,
            "mode": "masked" if masked else "status",
        }

    def _application_variable(self, application_uuid: str, key: str) -> JsonObject:
        self._identifier(key, "variable key")
        matches = [
            row
            for row in self._application_env_rows(
                application_uuid, required_permission="read:sensitive"
            )
            if row.get("key") == key
        ]
        if len(matches) != 1:
            raise ValueError("The requested application variable is absent or ambiguous")
        return matches[0]

    def prepare_application_variable_read(
        self, application_uuid: str, key: str
    ) -> JsonObject:
        """First call: validate scoped metadata, issue a short-lived one-use challenge."""
        variable = self._application_variable(application_uuid, key)
        # Enforce forbidden scopes without returning the candidate secret.
        app_variable_value(variable)
        challenge = self._read_confirmations.issue(
            self.account.id, application_uuid, key
        )
        return {
            "application_uuid": application_uuid,
            "key": key,
            "confirmation_token": challenge,
            "expires_in_seconds": self._read_confirmations.settings.confirmation_ttl_seconds,
            "status": "separate_confirmation_required",
            "permission_required": "Coolify read:sensitive and independent operator authority",
            "value_exposed": False,
        }

    def confirm_application_variable_read(
        self,
        application_uuid: str,
        key: str,
        *,
        confirmation_token: str,
        permission_confirmed: bool,
        purpose: str,
    ) -> JsonObject:
        """Second call: consume the scoped challenge and revalidate current provider state."""
        self._read_confirmations.consume(
            confirmation_token,
            account=self.account.id,
            application=application_uuid,
            variable=key,
            permission_confirmed=permission_confirmed,
            purpose=purpose,
        )
        variable = self._application_variable(application_uuid, key)
        value = app_variable_value(variable)
        return {
            "application_uuid": application_uuid,
            "key": key,
            "value": value,
            "value_length": len(value),
            "read_confirmed": True,
            "shared_value_exposed": False,
        }

    def application_logs(
        self,
        uuid: str,
        *,
        lines: int = 200,
        service_name: str = "",
        show_timestamps: bool = True,
        offset: int | None = None,
        max_chars: int = 20_000,
    ) -> JsonObject:
        if isinstance(lines, bool) or not 1 <= lines <= 5000:
            raise ValueError("lines must be between 1 and 5000")
        validate_log_window(offset, max_chars)
        query = {
            "lines": str(lines),
            "show_timestamps": "true" if show_timestamps else "false",
        }
        if service_name:
            query["service_name"] = self._identifier(service_name, "service_name")
        raw = json_object(
            self._get(
                "/applications/" + self._identifier(uuid, "application_uuid") + "/logs",
                query=query,
                required_permission="read:sensitive",
            ),
            context="Coolify application logs",
        )
        return {
            "application_uuid": uuid,
            "service_name": service_name or None,
            "lines_requested": lines,
            **runtime_log_page(
                raw, credential=self.account.credential, offset=offset, max_chars=max_chars
            ),
        }

    def service_logs(
        self,
        uuid: str,
        sub_service_name: str,
        *,
        lines: int = 200,
        show_timestamps: bool = True,
        offset: int | None = None,
        max_chars: int = 20_000,
    ) -> JsonObject:
        if isinstance(lines, bool) or not 1 <= lines <= 5000:
            raise ValueError("lines must be between 1 and 5000")
        validate_log_window(offset, max_chars)
        query = {
            "sub_service_name": self._identifier(sub_service_name, "sub_service_name"),
            "lines": str(lines),
            "show_timestamps": "true" if show_timestamps else "false",
        }
        raw = json_object(
            self._get(
                "/services/" + self._identifier(uuid, "service_uuid") + "/logs",
                query=query,
                required_permission="read:sensitive",
            ),
            context="Coolify service logs",
        )
        return {
            "service_uuid": uuid,
            "sub_service_name": sub_service_name,
            "lines_requested": lines,
            **runtime_log_page(
                raw, credential=self.account.credential, offset=offset, max_chars=max_chars
            ),
        }

    def restart_application(self, uuid: str, *, confirm: bool = False) -> JsonObject:
        self._confirmation(confirm)
        raw = json_object(
            self._post("/applications/" + self._identifier(uuid, "application_uuid") + "/restart"),
            context="Coolify restart",
        )
        return {
            "application_uuid": uuid,
            **_project(raw, ("message", "deployment_uuid")),
            "operation": "restart",
            "state": "submitted",
        }

    def restart_service(
        self, uuid: str, *, confirm: bool = False, pull_latest: bool = False
    ) -> JsonObject:
        """Restart one Coolify service resource; not a physical host."""
        self._confirmation(confirm)
        raw = json_object(
            self._post(
                "/services/" + self._identifier(uuid, "service_uuid") + "/restart",
                query={"latest": "true" if pull_latest else "false"},
            ),
            context="Coolify service restart",
        )
        return {
            "service_uuid": uuid,
            **_project(raw, ("message",)),
            "operation": "restart_service",
            "state": "submitted",
            "pull_latest": pull_latest,
        }

    def deploy_application(
        self, uuid: str, *, confirm: bool = False, force_rebuild: bool = False
    ) -> JsonObject:
        self._confirmation(confirm)
        raw = json_object(
            self._post(
                "/deploy",
                query={
                    "uuid": self._identifier(uuid, "application_uuid"),
                    "force": "true" if force_rebuild else "false",
                },
            ),
            context="Coolify deploy",
        )
        rows = json_object_list(raw.get("deployments"), context="Coolify deployment requests")
        return {
            "application_uuid": uuid,
            "deployments": [
                _project(row, ("resource_uuid", "deployment_uuid", "message")) for row in rows
            ],
            "operation": "deploy",
            "state": "submitted",
            "force_rebuild": force_rebuild,
        }

    def deployments(self) -> JsonValue:
        rows = json_object_list(self._get("/deployments"), context="Coolify deployments")
        return [_project(row, _DEPLOYMENT_FIELDS) for row in rows]

    def deployment(self, uuid: str) -> JsonObject:
        raw = json_object(
            self._get("/deployments/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify deployment",
        )
        return _project(raw, _DEPLOYMENT_FIELDS)

    def deployment_logs(
        self, uuid: str, *, offset: int | None = None, max_chars: int = 20_000
    ) -> JsonObject:
        # Validate before contacting the provider, including when it omits logs.
        validate_log_window(offset, max_chars)
        raw = json_object(
            self._get(
                "/deployments/" + urllib.parse.quote(uuid, safe=""),
                required_permission="read:sensitive",
            ),
            context="Coolify deployment",
        )
        return {
            **_project(raw, _DEPLOYMENT_FIELDS),
            **deployment_log_page(
                raw, credential=self.account.credential, offset=offset, max_chars=max_chars
            ),
        }

    def application_deployments(self, uuid: str) -> JsonValue:
        envelope = json_object(
            self._get("/deployments/applications/" + urllib.parse.quote(uuid, safe="")),
            context="Coolify application deployments",
        )
        rows = json_object_list(
            envelope.get("deployments"),
            context="Coolify application deployments.deployments",
        )
        return {
            "deployments": [_project(row, _DEPLOYMENT_FIELDS) for row in rows],
            "count": len(rows),
        }

    def deploy_service(
        self, uuid: str, *, confirm: bool = False, force_rebuild: bool = False
    ) -> JsonObject:
        """Deploy exactly one Coolify Service resource."""
        self._confirmation(confirm)
        raw = json_object(
            self._post(
                "/deploy",
                query={
                    "uuid": self._identifier(uuid, "service_uuid"),
                    "force": "true" if force_rebuild else "false",
                },
            ),
            context="Coolify service deploy",
        )
        rows = json_object_list(raw.get("deployments"), context="Coolify deployment requests")
        return {
            "service_uuid": uuid,
            "deployments": [
                _project(row, ("resource_uuid", "deployment_uuid", "message")) for row in rows
            ],
            "operation": "deploy_service",
            "state": "submitted",
            "force_rebuild": force_rebuild,
        }

    def account_summary(self) -> JsonObject:
        return json_object(
            {
                **self.account.model_dump(mode="json", exclude={"credential"}),
                "credential_configured": True,
                "permission_contract": (
                    "read for metadata; read:sensitive for logs/variable values; "
                    "deploy for restart/deploy"
                ),
                "required_permissions": {
                    "resource_metadata": "read",
                    "application_variable_metadata": "read",
                    "runtime_and_deployment_logs": "read:sensitive",
                    "shared_variable_status_and_mask": "read:sensitive",
                    "confirmed_application_variable_value": "read:sensitive",
                    "restart_and_deploy": "deploy",
                },
                "effective_token_permissions_verified": False,
                "permission_diagnostics": (
                    "Required permissions are documented, not inferred from the "
                    "configured token. An API 403 identifies the operation's required "
                    "permission and explains possible scope/owner restrictions."
                ),
            },
            context="Coolify account summary",
        )
