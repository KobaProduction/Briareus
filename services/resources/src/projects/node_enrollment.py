"""Human enrollment boundary and Resources-owned dependency composition."""

import hashlib
import json
from collections.abc import Awaitable, Callable

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from common.platform_db import PlatformDatabase
from projects.application.node_enrollment import EnrollmentRequest, EnrollmentTarget, EnrollNode
from projects.domain.execution_journal import JournalConflict, JournalRejected
from projects.domain.node_administration import (
    NodeConflict,
    NodeForbidden,
    NodeMissing,
    NodeReceiptUnavailable,
    OperatorAuthority,
)
from projects.infrastructure.node_administration import NodeItemPayload, NodeSummaryPayload
from projects.infrastructure.node_enrollment import SqlEnrollmentStore, canonical_node_key
from projects.node_control import NodeControl, NodeUnavailable
from projects.presentation.node_commands import NodeCommand


def enrollment_request(command: NodeCommand) -> EnrollmentRequest:
    if (
        command.action not in {"setup", "pair", "enable", "budget"}
        or command.node_uuid is None
        or command.expected_sequence is None
        or command.registration is not None
        or command.name
        or (command.action == "pair") != bool(command.public_key)
        or (command.action == "budget") != (command.budget is not None)
    ):
        raise HTTPException(422, "Exact node enrollment command required")
    payload = command.model_dump(
        mode="json",
        exclude={"identity_expires_at", "module"}
        | ({"budget"} if command.budget is None else set()),
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return EnrollmentRequest(
        command.operation_uuid,
        command.actor_uuid,
        command.project_uuid,
        command.node_uuid,
        command.expected_sequence,
        command.action,
        digest,
        command.public_key,
        command.budget,
    )


async def enroll(
    command: NodeCommand,
    *,
    database: PlatformDatabase,
    cipher: Fernet,
    authorize: Callable[[NodeCommand], Awaitable[OperatorAuthority]],
    remote: NodeControl | None = None,
) -> JSONResponse:
    request = enrollment_request(command)
    try:
        remote = remote or NodeControl.from_environment()
        use_case = EnrollNode(
            SqlEnrollmentStore(database, cipher),
            remote,
            lambda: authorize(command),
            canonical_node_key,
        )
        result = await use_case.execute(request)
        if isinstance(result, EnrollmentTarget):
            return JSONResponse(
                {
                    "setup": remote.setup_target(
                        result.record, runtime_uid=result.runtime_uid, endpoint=result.endpoint
                    ).model_dump(mode="json")
                }
            )
        return JSONResponse(
            NodeItemPayload(item=NodeSummaryPayload.from_record(result)).model_dump(mode="json")
        )
    except (NodeConflict, JournalConflict) as error:
        raise HTTPException(409, str(error)) from None
    except (NodeForbidden, JournalRejected) as error:
        raise HTTPException(403, str(error)) from None
    except NodeMissing as error:
        raise HTTPException(404, str(error)) from None
    except NodeReceiptUnavailable as error:
        raise HTTPException(503, str(error)) from None
    except NodeUnavailable:
        raise HTTPException(
            503, "Authenticated node control unavailable; reconcile before retry"
        ) from None
    except IntegrityError:
        raise HTTPException(409, "Node operation conflicts; retry the same operation") from None
    except (ValueError, KeyError, OSError):
        raise HTTPException(422, "Invalid node enrollment configuration") from None
