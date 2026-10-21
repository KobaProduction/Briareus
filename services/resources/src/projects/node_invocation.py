"""Short private account views from the existing project connection owner.

Authorization calls this ONLY after its exact current Cedar effect decision.
Resources independently rechecks Platform membership, the physical Node
binding and project ownership of the selected IntegrationRow. This endpoint
is never a browser API, global account store or user-supplied credential lease.
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, UUID4, field_validator
from sqlalchemy import select

from node_protocol.control import canonical
from node_protocol.effect import NodeWorkspaceBinding
from projects._provider_registry import ProviderOptions
from projects._resource_persistence import IntegrationRow


class InvocationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issuer: str = Field(min_length=12, max_length=512)
    subject: str = Field(min_length=1, max_length=256)
    project_uuid: UUID4
    actor_uuid: UUID4
    agent_session_uuid: UUID4
    grant_revision: int = Field(strict=True, ge=1)
    identity_expires_at: datetime
    module: Literal["svc", "infrastructure"]
    tool: str = Field(min_length=1, max_length=128)
    arguments: dict = Field(max_length=64)
    binding: NodeWorkspaceBinding

    @field_validator("tool")
    @classmethod
    def exact_tool(cls, value):
        from node_protocol.module_effects import TOOL_NAME
        if TOOL_NAME.fullmatch(value) is None:
            raise ValueError("Exact bounded tool selector required")
        return value


def selection(module, tool, arguments):
    """Select a provider/account; this does not assert that a tool exists."""
    if tool == module + "_operation_start":
        if set(arguments) != {"tool", "arguments"} or not isinstance(arguments.get("arguments"), dict):
            raise ValueError("Exact original provider invocation required")
        original = arguments.get("tool")
        if not isinstance(original, str) or original.startswith(module + "_operation_"):
            raise ValueError("Original provider tool required")
        return selection(module, original, arguments["arguments"])
    if tool in {module + "_operation_poll", module + "_operation_cancel"}:
        allowed = {"operation_id", "tool", "account_id"} | ({"provider"} if module == "infrastructure" else set())
        if set(arguments) - allowed:
            raise ValueError("Exact bound provider continuation required")
        original = arguments.get("tool")
        if not isinstance(original, str) or original.startswith(module + "_operation_"):
            raise ValueError("Original provider tool required")
        # Supervisor independently compares this selector to the captured start
        # arguments before resuming. Resources returns only that one current
        # project's credential, never all credentials for an operation handle.
        selector = arguments.get("account_id")
        selected = {} if selector is None else {"account_id": selector}
        if module == "infrastructure" and arguments.get("provider") is not None:
            selected["provider"] = arguments["provider"]
        return selection(module, original, selected)
    if module == "svc":
        if tool == "github_accounts":
            return "github", None
        if tool == "accounts":
            return "gitlab", None
        provider = "github" if tool.startswith("github_") else "gitlab"
    elif module == "infrastructure":
        if tool == "observability_sources":
            provider = arguments.get("provider")
            if provider not in {None, "signoz", "coolify"}:
                raise ValueError("Unknown infrastructure provider")
            return provider, None
        if tool == "observability_connection":
            provider = arguments.get("provider")
            if provider not in {"signoz", "coolify"}:
                raise ValueError("Explicit infrastructure provider required")
        elif tool in {"observability_search_logs", "observability_search_traces", "observability_query_telemetry",
                      "observability_list_services", "observability_field_keys", "observability_field_values"}:
            provider = "signoz"
        else:
            provider = "coolify"
    else:
        raise ValueError("Private provider module required")
    selector = arguments.get("account_id")
    if not isinstance(selector, str) or not 0 < len(selector) <= 128 or selector.strip() != selector:
        raise ValueError("One explicit project account selector required")
    return provider, selector


def public_account(row):
    options = row.provider_settings
    endpoint = ProviderOptions.safe_url(options.get("base_url", ""))
    if not endpoint or row.provider not in {"github", "gitlab", "coolify", "signoz"}:
        raise ValueError("Current validated provider endpoint required")
    return {"id": str(row.id), "alias": row.alias, "provider": row.provider,
        "auth_type": row.auth_type, "base_url": endpoint,
        "external_id": options.get("external_id") or None,
        "verify_tls": True, "ca_cert_pem": options.get("ca_cert_pem") or None, "enabled": True,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}


async def project_accounts(database, cipher, command):
    provider, selector = selection(command.module, command.tool, command.arguments)
    providers = ({"github", "gitlab"} if command.module == "svc" else {"signoz", "coolify"})
    if provider is not None:
        providers &= {provider}
    async with database.transaction() as tx:
        statement = select(IntegrationRow).where(IntegrationRow.owner_project_id == command.project_uuid,
            IntegrationRow.owner_team_id.is_(None), IntegrationRow.deleted_at.is_(None),
            IntegrationRow.provider.in_(providers))
        if selector is not None:
            # Aliases are canonicalized by the existing connection owner.
            from sqlalchemy import or_
            from uuid import UUID
            try:
                selected_id = UUID(selector)
            except ValueError:
                selected_id = None
            statement = statement.where(or_(IntegrationRow.alias_key == selector.casefold(),
                IntegrationRow.id == selected_id) if selected_id else IntegrationRow.alias_key == selector.casefold())
        rows = list((await tx.scalars(statement.order_by(IntegrationRow.id).limit(65))).all())
        if len(rows) > 64 or selector is not None and len(rows) != 1:
            raise HTTPException(403, "Current project account unavailable")
        if any(row.owner_project_id != command.project_uuid or row.owner_team_id is not None
               or row.deleted_at is not None or row.provider not in providers for row in rows):
            raise HTTPException(403, "Current project account ownership mismatch")
        accounts = [public_account(row) for row in rows]
        if selector is not None:
            row = rows[0]
            envelope = json.loads(cipher.decrypt(row.encrypted_credential.encode()))
            if (not isinstance(envelope, dict) or set(envelope) != {"connection", "project", "token"}
                or envelope["connection"] != str(row.id) or envelope["project"] != str(command.project_uuid)
                or not isinstance(envelope["token"], str) or not 0 < len(envelope["token"]) <= 32768):
                raise ValueError("Current connection credential binding invalid")
            accounts[0]["credential"] = envelope["token"]
    context = {"accounts": accounts}
    if command.module == "svc" and selector is not None:
        # Policies belong to the exact selected project connection; refresh them
        # alongside its current credentials on every effect, never a global account.
        from projects.connection_forms import GitPolicyForm, GitLabPolicyForm
        policy_type = GitPolicyForm if provider == "github" else GitLabPolicyForm
        policy = policy_type.model_validate(rows[0].provider_settings.get("git_policy", {}))
        runtime_keys = {"local_first_guidance", "local_git_transport_enabled", "remote_source_mutations_enabled"}
        values = policy.model_dump(mode="json")
        context["policies"] = {
            provider: {key: value for key, value in values.items() if key not in runtime_keys
                       and (provider == "github" or key == "protected_branches")},
            provider + "_runtime": {key: values[key] for key in runtime_keys},
        }
    if len(canonical(context)) > 8192:
        raise ValueError("Bounded private invocation context required")
    return context


def invocation_router(*, platform, cipher, resolve_database, resolve_binding):
    router = APIRouter()

    @router.post("/internal/v1/resources/node-invocation", include_in_schema=False)
    async def invoke(request: Request):
        if request.scope.get("briareus.service_peer") != "briareus:authorization":
            raise HTTPException(403, "Current Authorization owner required")
        try:
            command = InvocationCommand.model_validate(await request.json())
            now = datetime.now(UTC)
            if (command.identity_expires_at.tzinfo is None
                or not now < command.identity_expires_at <= now + timedelta(seconds=30)
                or command.binding.project_uuid != command.project_uuid
                or not time.time() < command.binding.expires_at <= time.time() + 5):
                raise HTTPException(403, "Current project invocation required")
            status, actor = await platform.call("/internal/v1/platform/oidc/actor-context", {
                "issuer": command.issuer, "subject": command.subject, "project_uuid": str(command.project_uuid)})
            if status != 200 or not isinstance(actor, dict):
                raise HTTPException(403 if status == 403 else 503, "Current Platform membership unavailable")
            expiry = datetime.fromisoformat(actor["expires_at"])
            if (actor.get("issuer") != command.issuer or actor.get("subject") != command.subject
                or actor.get("actor_uuid") != str(command.actor_uuid)
                or actor.get("project_uuid") != str(command.project_uuid)
                or not isinstance(actor.get("permissions"), (list, tuple))
                or "use_resources" not in actor.get("permissions", [])
                or expiry.tzinfo is None or not now < expiry <= now + timedelta(seconds=30)):
                raise HTTPException(403, "Current project resource access required")
            actual = await resolve_binding(command.project_uuid, command.module, request)
            if actual.model_dump(exclude={"expires_at"}) != command.binding.model_dump(exclude={"expires_at"}):
                raise HTTPException(403, "Current project placement changed")
            database = resolve_database()
            if database is None:
                raise HTTPException(503, "Resources owner unavailable")
            context = await project_accounts(database, cipher, command)
            deadline = min(command.identity_expires_at, expiry).timestamp()
            expires = min(int(time.time()) + 5, int(deadline), actual.expires_at, command.binding.expires_at)
            if expires <= time.time():
                raise HTTPException(403, "Current invocation expired")
            return JSONResponse({"context": context, "expires_at": expires}, headers={"Cache-Control": "no-store"})
        except HTTPException:
            raise
        except Exception:
            # In particular, decrypt/validation errors must not echo credentials.
            raise HTTPException(503, "Private current invocation unavailable") from None

    return router
