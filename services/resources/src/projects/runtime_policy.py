"""Runtime policy management boundary; changes apply on explicit placement updates."""

import hashlib
import json
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from common.platform_db import PlatformDatabase
from node_protocol.models import RuntimePolicy
from projects.application.runtime_settings import ManageRuntimeSettings
from projects.domain.runtime_settings import (
    RuntimeNodeMissing,
    RuntimeOverrides,
    RuntimePolicyConflict,
    RuntimePolicyForbidden,
    RuntimePolicyIdentity,
    resolve_runtime,
)
from projects.infrastructure.runtime_settings import (
    RuntimePolicyEnvelope,
    RuntimePolicyPayload,
    RuntimeSources,
    SqlRuntimeSettingsTransactions,
    effective_payload,
    override_record,
    source_payload,
)
from projects.infrastructure.runtime_settings import (
    resolved_configuration as resolved_configuration,
)

if TYPE_CHECKING:
    from projects.presentation.node_commands import NodeCommand


class ResolvedPolicy(NamedTuple):
    policy: RuntimePolicy
    sources: RuntimeSources


def resolve_policy(
    server: RuntimeOverrides | None = None, node: RuntimeOverrides | None = None
) -> ResolvedPolicy:
    resolution = resolve_runtime(server or RuntimeOverrides(), node or RuntimeOverrides())
    return ResolvedPolicy(effective_payload(resolution), source_payload(resolution))


utc_now = partial(datetime.now, UTC)


def command_overrides(command: "NodeCommand") -> RuntimeOverrides | None:
    if command.policy_scope == "node" and command.node_uuid is None:
        raise HTTPException(422, "Node required")
    if command.policy_scope == "server" and command.node_uuid is not None:
        raise HTTPException(422, "Server policy has no node")
    if (
        command.module
        or command.registration
        or command.name
        or command.public_key
        or command.budget
    ):
        raise HTTPException(422, "Exact runtime policy command required")
    if command.action == "runtime_policy_get":
        if command.policy_values is not None:
            raise HTTPException(422, "Read cannot write policy")
        return None
    if command.policy_values is None or command.expected_policy_sequence is None:
        raise HTTPException(422, "Explicit overrides and current sequence required")
    return override_record(command.policy_values)


async def policy_command(
    command: "NodeCommand", *, database: PlatformDatabase, cipher: Fernet, expiry: datetime
) -> JSONResponse:
    overrides = command_overrides(command)
    digest = hashlib.sha256(
        json.dumps(
            command.model_dump(mode="json", exclude={"identity_expires_at"}), sort_keys=True
        ).encode()
    ).hexdigest()
    identity = RuntimePolicyIdentity(
        command.operation_uuid,
        command.actor_uuid,
        command.project_uuid,
        digest,
        command.expected_policy_sequence,
    )
    try:
        result = await ManageRuntimeSettings(
            SqlRuntimeSettingsTransactions(database, cipher), utc_now
        ).execute(
            identity,
            scope=command.policy_scope,
            node_uuid=command.node_uuid,
            overrides=overrides,
            expiry=expiry,
        )
    except RuntimePolicyConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except RuntimePolicyForbidden as exc:
        raise HTTPException(403, str(exc)) from None
    except RuntimeNodeMissing as exc:
        raise HTTPException(404, str(exc)) from None
    payload = RuntimePolicyEnvelope(runtime_policy=RuntimePolicyPayload.from_view(result))
    return JSONResponse(payload.model_dump(mode="json"))
