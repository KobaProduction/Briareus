"""Canonical codec for the existing private operation fingerprint preimage."""

import hashlib
import json
from uuid import UUID

from pydantic import BaseModel

from project_runtime_client.domain.authorization import ProjectAccessDenied, ProjectAction
from project_runtime_client.domain.identifiers import valid_uuid


def canonical_request_fingerprint(
    *,
    project_id: UUID,
    session_uuid: UUID,
    action: ProjectAction,
    request_uuid: UUID,
    backend: str,
    tool: str,
    arguments: BaseModel,
) -> str:
    """Domain-separated digest of the *normalized* concrete private command.

    A digest is a binding label, NOT an HMAC/signed authorization proof. Any
    future C1-B2 transport must pass this exact digest as its independently
    routed `expected_fingerprint` to Backend A5's verifier.
    """
    if not isinstance(backend, str):
        raise ProjectAccessDenied("PROJECT_OPERATION_FINGERPRINT_INVALID")
    if not isinstance(tool, str):
        raise ProjectAccessDenied("PROJECT_OPERATION_FINGERPRINT_INVALID")
    if (
        not valid_uuid(request_uuid, version=4)
        or not valid_uuid(session_uuid, version=4)
        or not valid_uuid(project_id)
        or not isinstance(arguments, BaseModel)
    ):
        raise ProjectAccessDenied("PROJECT_OPERATION_FINGERPRINT_INVALID")
    try:
        normalized: object = arguments.model_dump(mode="json")
        if not isinstance(normalized, dict):
            raise ValueError("Object-shaped private command required")
        encoded = json.dumps(
            [
                "private-project-op-v1",
                str(project_id),
                str(session_uuid),
                str(request_uuid),
                action,
                backend,
                tool,
                normalized,
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProjectAccessDenied("PROJECT_OPERATION_FINGERPRINT_INVALID") from exc
    if len(encoded) > 600000:
        raise ProjectAccessDenied("PROJECT_OPERATION_FINGERPRINT_TOO_LARGE")
    return hashlib.sha256(encoded).hexdigest()
