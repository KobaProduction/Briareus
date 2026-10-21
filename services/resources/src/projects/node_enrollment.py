"""Operator enrollment; remote I/O never holds a database row lock."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import serialization
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from node_protocol.replies import NodeReplyVerifier
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import NodeRow
from projects.node_control import NodeControl, NodeUnavailable, node_record


async def enroll(command, *, database, cipher, authorize, remote=None):
    from projects.node_management import summary
    if (command.node_uuid is None or command.expected_sequence is None or command.registration is not None
        or command.name or (command.action == "pair") != bool(command.public_key)):
        raise HTTPException(422, "Exact node enrollment command required")
    payload = command.model_dump(mode="json", exclude={"identity_expires_at", "module"} | ({"budget"} if command.budget is None else set()))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    action = "node." + command.action
    try:
        remote = remote or NodeControl.from_environment()
        async with database.transaction() as tx:
            existing = await tx.scalar(select(OwnerCommandRow).where(
                OwnerCommandRow.operation_uuid == command.operation_uuid, OwnerCommandRow.operation == action))
            if existing:
                if (existing.fingerprint != digest or existing.actor_scope != str(command.actor_uuid)
                    or existing.project_scope != str(command.project_uuid) or existing.state != "completed"):
                    raise HTTPException(409, "Operation identity conflict")
                outcome = json.loads(cipher.decrypt(existing.encrypted_outcome.encode()))
                if outcome["digest"] != digest or outcome["operation"] != str(command.operation_uuid):
                    raise HTTPException(503, "Operation receipt unavailable")
                await authorize(command)
                return JSONResponse(outcome["result"])
            row = await tx.get(NodeRow, command.node_uuid)
            if row is None or row.deleted_at is not None:
                raise HTTPException(404, "Node not found")
            if row.sequence != command.expected_sequence:
                raise HTTPException(409, "Node configuration changed")
            if command.action == "setup":
                return JSONResponse({"setup": remote.setup(row)})
            record = node_record(row)
            endpoint = row.endpoint
            pinned = row.public_key
        # No remote public-key discovery/TOFU. Operator supplies the key obtained
        # from the provisioned node through its trusted deployment channel.
        if command.action == "pair":
            verifier = NodeReplyVerifier(command.public_key.encode())
            public_key = verifier.key.public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo).decode()
            if pinned and pinned != public_key:
                raise HTTPException(409, "Node identity rotation requires separate recovery")
            observation = await remote.call(endpoint=endpoint, public_key=public_key,
                node_uuid=record.id, operation_uuid=command.operation_uuid, sequence=command.expected_sequence)
            if (observation.get("node_uuid") != str(record.id)
                or type(observation.get("enabled")) is not bool
                or type(observation.get("sequence")) is not int):
                raise NodeUnavailable("Invalid node inventory")
        else:
            if not pinned:
                raise HTTPException(409, "Verified node identity required")
            public_key = pinned
            candidate = (record.model_copy(update={"budget": command.budget}) if command.action == "budget"
                         else record.model_copy(update={"enabled": True}))
            observation = await remote.call(endpoint=endpoint, public_key=pinned, node_uuid=record.id,
                operation_uuid=command.operation_uuid, sequence=command.expected_sequence + 1,
                action="configure", record=candidate)
            if (observation.get("node_uuid") != str(record.id) or observation.get("enabled") is not candidate.enabled
                or observation.get("sequence") != command.expected_sequence + 1):
                raise NodeUnavailable("Node configuration not acknowledged")
        _, expiry = await authorize(command)
        async with database.transaction() as tx:
            row = await tx.scalar(select(NodeRow).where(NodeRow.id == command.node_uuid,
                NodeRow.deleted_at.is_(None)).with_for_update())
            if (row is None or row.sequence != command.expected_sequence or row.endpoint != endpoint
                or row.public_key != pinned):
                raise HTTPException(409, "Node configuration changed; reconcile enrollment")
            if expiry <= datetime.now(UTC):
                raise HTTPException(403, "Platform proof expired")
            row.public_key = public_key
            row.enabled = True if command.action == "enable" else row.enabled
            if command.action == "budget":
                row.budget = candidate.budget.model_dump(mode="json")
            row.last_seen_at = datetime.now(UTC)
            row.sequence += 1
            await tx.flush()
            result = {"item": summary(row)}
            tx.add(OwnerCommandRow(operation_uuid=command.operation_uuid,
                actor_scope=str(command.actor_uuid), project_scope=str(command.project_uuid),
                operation=action, key=str(command.operation_uuid), fingerprint=digest,
                expected_owner_revision=str(command.expected_sequence), state="completed",
                encrypted_outcome=cipher.encrypt(json.dumps({"operation": str(command.operation_uuid),
                    "digest": digest, "result": result}).encode()).decode(),
                expires_at=datetime.now(UTC) + timedelta(days=7)))
            tx.add(OwnerAuditRow(operation_uuid=command.operation_uuid, actor_user_id=command.actor_uuid,
                project_id=command.project_uuid, action=action, object_id=str(row.id),
                owner_revision=str(row.sequence), details={"scope": row.scope}))
        return JSONResponse(result)
    except NodeUnavailable:
        raise HTTPException(503, "Authenticated node control unavailable; reconcile before retry") from None
    except IntegrityError:
        raise HTTPException(409, "Node operation conflicts; retry the same operation") from None
    except (ValueError, KeyError, OSError):
        raise HTTPException(422, "Invalid node enrollment configuration") from None
