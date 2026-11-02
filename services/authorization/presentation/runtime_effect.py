"""Consume original effect arguments at ingress; only their digest enters the use case."""

import hashlib

from pydantic import UUID4, BaseModel, ConfigDict, Field, StrictInt, StrictStr

from authorization.application.runtime_effects import RuntimeEffectCall
from runtime_peer import canonical_json


class _EffectHeaders(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool: StrictStr
    agent_session_uuid: UUID4
    expected_grant_revision: StrictInt = Field(ge=1)
    operation_uuid: UUID4


def decode_runtime_effect(value: object) -> RuntimeEffectCall:
    if isinstance(value, RuntimeEffectCall):
        return value
    if not isinstance(value, dict) or len(value) > 12:
        raise ValueError("Bounded runtime command object required")
    arguments = value.get("arguments")
    if not isinstance(arguments, dict) or len(arguments) > 16:
        raise ValueError("Bounded effect arguments required")
    if not all(isinstance(key, str) for key in value):
        raise ValueError("Runtime command keys must be strings")
    headers = _EffectHeaders.model_validate(
        {key: item for key, item in value.items() if key != "arguments"}
    )
    return RuntimeEffectCall(
        headers.tool,
        hashlib.sha256(canonical_json(arguments)).hexdigest(),
        headers.agent_session_uuid,
        headers.expected_grant_revision,
        headers.operation_uuid,
    )
