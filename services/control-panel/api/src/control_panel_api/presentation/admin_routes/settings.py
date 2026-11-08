from __future__ import annotations

import asyncio
import json
from hashlib import sha256

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_github_policy import GitHubRuntimePolicy
from briareus_gitlab_policy import GitLabRuntimePolicy
from briareus_json_values import JsonObject, json_object
from briareus_mcp_policy import McpRuntimePolicy
from briareus_terminal_policy import TerminalRuntimePolicy
from fastapi import APIRouter, HTTPException, Request, status

from control_panel_api.domain.configuration import ControlPanelConfig

from .context import WebApiContext
from .contracts import SettingsPayload, WebApiServices


class SettingsRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/settings", self.settings_get, methods=["GET"])
        router.add_api_route("/settings", self.settings_update, methods=["PUT"])
        router.add_api_route("/settings/cleanup-logs", self.settings_cleanup, methods=["POST"])

    async def reverse_settings(
        self,
        api: WebApiServices,
        *,
        idle_timeout: float | None = None,
    ) -> JsonObject:
        if self.context.discovery is not None and not await self.context.discovery.connected(
            "ghidra"
        ):
            if idle_timeout is not None and idle_timeout != 900.0:
                raise HTTPException(
                    503, detail={"code": "service_unavailable", "service": "ghidra"}
                )
            return {
                "idle_timeout_seconds": 900.0,
                "auto_release_enabled": True,
                "source": "unavailable",
            }
        if idle_timeout is not None:
            return await api.reverse.set_idle_timeout(idle_timeout)
        return await api.reverse.session_settings()

    def settings_revision(self, snapshot: JsonObject) -> str:
        analysis = json_object(snapshot["analysis"], context="analysis settings")
        idle_raw = analysis.get("idle_timeout_seconds", 900.0)
        idle_timeout = float(idle_raw) if isinstance(idle_raw, (int, float)) else 900.0
        versioned = {
            "management": snapshot["management"],
            "terminal": snapshot["terminal"],
            "mcp": snapshot["mcp"],
            "browser": snapshot["browser"],
            "github": snapshot["github"],
            "gitlab": snapshot["gitlab"],
            "analysis_idle_timeout_seconds": idle_timeout,
        }
        encoded = json.dumps(versioned, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()

    async def settings_snapshot(self, api: WebApiServices) -> JsonObject:
        (
            config,
            terminal_policy,
            mcp_policy,
            browser_policy,
            github_policy,
            gitlab_policy,
        ) = await asyncio.gather(
            asyncio.to_thread(api.config.get),
            asyncio.to_thread(api.runtime_settings.terminal_policy),
            asyncio.to_thread(api.runtime_settings.mcp_policy),
            asyncio.to_thread(api.runtime_settings.browser_policy),
            asyncio.to_thread(api.runtime_settings.github_policy),
            asyncio.to_thread(api.runtime_settings.gitlab_policy),
        )
        try:
            reverse_settings = await self.reverse_settings(api)
            reverse_error = ""
        except Exception as exc:
            reverse_settings = {
                "idle_timeout_seconds": 900.0,
                "auto_release_enabled": True,
                "source": "unavailable",
            }
            reverse_error = str(exc)
        snapshot: JsonObject = {
            "management": config.model_dump(mode="json"),
            "terminal": terminal_policy.model_dump(mode="json"),
            "mcp": mcp_policy.model_dump(mode="json"),
            "browser": browser_policy.model_dump(mode="json"),
            "github": github_policy.model_dump(mode="json"),
            "gitlab": gitlab_policy.model_dump(mode="json"),
            "analysis": reverse_settings,
            "analysis_error": reverse_error,
        }
        snapshot["revision"] = self.settings_revision(snapshot)
        return snapshot

    async def settings_get(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        return await self.settings_snapshot(self.context.available())

    async def settings_update(self, payload: SettingsPayload, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        async with self.context.settings_update_lock:
            current = await self.check_revision(api, payload)
            management = ControlPanelConfig(
                logging_enabled=payload.logging_enabled,
                logging_capture_payloads=payload.logging_capture_payloads,
                logging_retention_days=payload.logging_retention_days,
                logging_max_records=payload.logging_max_records,
                maintenance_interval_minutes=payload.maintenance_interval_minutes,
            )
            terminal_policy = TerminalRuntimePolicy(
                max_exec_timeout_seconds=payload.terminal_max_exec_timeout_seconds,
                max_job_runtime_seconds=payload.terminal_max_job_runtime_seconds,
            )
            mcp_policy = McpRuntimePolicy(call_timeout_seconds=payload.mcp_call_timeout_seconds)
            if current is not None:
                current_browser = BrowserRuntimePolicy.model_validate(current["browser"])
            else:
                current_browser = await asyncio.to_thread(api.runtime_settings.browser_policy)
            try:
                browser_policy = self.browser_policy(payload, current_browser)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            browser_token = (
                payload.browser_extension_token
                if "browser_extension_token" in payload.model_fields_set
                and payload.browser_extension_token.strip()
                else None
            )
            clear_browser_token = (
                payload.browser_clear_extension_token
                if "browser_clear_extension_token" in payload.model_fields_set
                else False
            )
            if browser_token is not None and clear_browser_token:
                raise HTTPException(
                    status_code=400,
                    detail="cannot set and clear external browser extension token together",
                )
            try:
                github_policy = await self.github_policy(api, payload, current)
                gitlab_policy = await self.gitlab_policy(api, payload, current)
                reverse_settings = await self.reverse_settings(
                    api, idle_timeout=payload.reverse_idle_timeout_seconds
                )
                (
                    saved_management,
                    saved_terminal,
                    saved_mcp,
                    saved_browser,
                    saved_github,
                    saved_gitlab,
                ) = await asyncio.gather(
                    asyncio.to_thread(api.config.update, management),
                    asyncio.to_thread(api.runtime_settings.update_terminal_policy, terminal_policy),
                    asyncio.to_thread(api.runtime_settings.update_mcp_policy, mcp_policy),
                    asyncio.to_thread(
                        api.runtime_settings.update_browser_policy,
                        browser_policy,
                        extension_token=browser_token,
                        clear_extension_token=clear_browser_token,
                    ),
                    asyncio.to_thread(api.runtime_settings.update_github_policy, github_policy),
                    asyncio.to_thread(api.runtime_settings.update_gitlab_policy, gitlab_policy),
                )
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            await self.disconnect_changed_browser(api, saved_browser, current_browser)
            response: JsonObject = {
                "management": saved_management.model_dump(mode="json"),
                "terminal": saved_terminal.model_dump(mode="json"),
                "mcp": saved_mcp.model_dump(mode="json"),
                "browser": saved_browser.model_dump(mode="json"),
                "github": saved_github.model_dump(mode="json"),
                "gitlab": saved_gitlab.model_dump(mode="json"),
                "analysis": reverse_settings,
                "analysis_error": "",
            }
            response["revision"] = self.settings_revision(response)
            await self.context.publish_management_event(api, "settings.updated", response)
            return response

    async def settings_cleanup(self, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        removed = await asyncio.to_thread(api.audit.cleanup)
        response: JsonObject = {"removed": removed}
        await self.context.publish_management_event(api, "calls.retention_applied", response)
        return response

    async def check_revision(
        self, api: WebApiServices, payload: SettingsPayload
    ) -> JsonObject | None:
        current: JsonObject | None = None
        if payload.expected_revision:
            try:
                current = await self.settings_snapshot(api)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if payload.expected_revision != current["revision"]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "settings_conflict",
                        "message": "settings changed since they were loaded; reload before saving",
                        "current_revision": current["revision"],
                    },
                )
        return current

    def browser_policy(
        self, payload: SettingsPayload, current_browser: BrowserRuntimePolicy
    ) -> BrowserRuntimePolicy:
        return BrowserRuntimePolicy(
            external_enabled=payload.browser_external_enabled
            if "browser_external_enabled" in payload.model_fields_set
            else current_browser.external_enabled,
            external_mcp_url=payload.browser_external_mcp_url
            if "browser_external_mcp_url" in payload.model_fields_set
            else current_browser.external_mcp_url,
            call_timeout_seconds=payload.browser_call_timeout_seconds
            if "browser_call_timeout_seconds" in payload.model_fields_set
            else current_browser.call_timeout_seconds,
            auto_disconnect_enabled=payload.browser_auto_disconnect_enabled
            if "browser_auto_disconnect_enabled" in payload.model_fields_set
            else current_browser.auto_disconnect_enabled,
            idle_timeout_seconds=payload.browser_idle_timeout_seconds
            if "browser_idle_timeout_seconds" in payload.model_fields_set
            else current_browser.idle_timeout_seconds,
            profile_dir_name=payload.browser_profile_dir_name
            if "browser_profile_dir_name" in payload.model_fields_set
            else current_browser.profile_dir_name,
            extension_token_configured=current_browser.extension_token_configured,
        )

    async def github_policy(
        self, api: WebApiServices, payload: SettingsPayload, current: JsonObject | None
    ) -> GitHubRuntimePolicy:
        github_fields = {
            "github_local_first_guidance",
            "github_local_git_transport_enabled",
            "github_remote_source_mutations_enabled",
        }
        if github_fields.issubset(payload.model_fields_set):
            github_policy = GitHubRuntimePolicy(
                local_first_guidance=payload.github_local_first_guidance,
                local_git_transport_enabled=payload.github_local_git_transport_enabled,
                remote_source_mutations_enabled=payload.github_remote_source_mutations_enabled,
            )
        else:
            if current is not None:
                current_github = GitHubRuntimePolicy.model_validate(current["github"])
            else:
                current_github = await asyncio.to_thread(api.runtime_settings.github_policy)
            github_policy = GitHubRuntimePolicy(
                local_first_guidance=payload.github_local_first_guidance
                if "github_local_first_guidance" in payload.model_fields_set
                else current_github.local_first_guidance,
                local_git_transport_enabled=payload.github_local_git_transport_enabled
                if "github_local_git_transport_enabled" in payload.model_fields_set
                else current_github.local_git_transport_enabled,
                remote_source_mutations_enabled=payload.github_remote_source_mutations_enabled
                if "github_remote_source_mutations_enabled" in payload.model_fields_set
                else current_github.remote_source_mutations_enabled,
            )
        return github_policy

    async def gitlab_policy(
        self, api: WebApiServices, payload: SettingsPayload, current: JsonObject | None
    ) -> GitLabRuntimePolicy:
        gitlab_fields = {
            "gitlab_local_first_guidance",
            "gitlab_local_git_transport_enabled",
            "gitlab_remote_source_mutations_enabled",
        }
        if gitlab_fields.issubset(payload.model_fields_set):
            gitlab_policy = GitLabRuntimePolicy(
                local_first_guidance=payload.gitlab_local_first_guidance,
                local_git_transport_enabled=payload.gitlab_local_git_transport_enabled,
                remote_source_mutations_enabled=payload.gitlab_remote_source_mutations_enabled,
            )
        else:
            if current is not None:
                current_gitlab = GitLabRuntimePolicy.model_validate(current["gitlab"])
            else:
                current_gitlab = await asyncio.to_thread(api.runtime_settings.gitlab_policy)
            gitlab_policy = GitLabRuntimePolicy(
                local_first_guidance=payload.gitlab_local_first_guidance
                if "gitlab_local_first_guidance" in payload.model_fields_set
                else current_gitlab.local_first_guidance,
                local_git_transport_enabled=payload.gitlab_local_git_transport_enabled
                if "gitlab_local_git_transport_enabled" in payload.model_fields_set
                else current_gitlab.local_git_transport_enabled,
                remote_source_mutations_enabled=payload.gitlab_remote_source_mutations_enabled
                if "gitlab_remote_source_mutations_enabled" in payload.model_fields_set
                else current_gitlab.remote_source_mutations_enabled,
            )
        return gitlab_policy

    async def disconnect_changed_browser(
        self,
        api: WebApiServices,
        saved_browser: BrowserRuntimePolicy,
        current_browser: BrowserRuntimePolicy,
    ) -> None:
        if saved_browser != current_browser:
            try:
                await api.web.external_disconnect()
            except Exception as exc:
                if api.realtime is not None:
                    await api.realtime.publish(
                        "browser.runtime", "external.policy_disconnect_failed", {"error": str(exc)}
                    )
