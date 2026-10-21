"""Platform invitation authority; Rauthy ce35a70f owns account/setup codes.

Grants and durable send intents use the existing Platform audit/outbox ledger.
No password, provider magic link or provider token is stored here.
"""
from __future__ import annotations

import asyncio
import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, ProxyHandler, build_opener

from sqlalchemy import select, text

from ._control_ledger import OwnerAuditRow, OwnerOutboxRow
from ._rauthy_user_links import RauthyUserLinkRow
from ._rauthy_user_status import _ID, _NoRedirect


def provisioning_error() -> str | None:
    if os.environ.get("RAUTHY_INVITATION_EMAIL_READY") != "1":
        return "RAUTHY_INVITATION_MAIL_UNCONFIGURED"
    path = Path("/var/lib/briareus-platform/rauthy-users-invite.key")
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or info.st_mode & 0o077 or not 1 <= info.st_size <= 4096:
            return "RAUTHY_INVITATION_KEY_UNAVAILABLE"
    except OSError:
        return "RAUTHY_INVITATION_KEY_UNAVAILABLE"
    return None


def create_provider_user(email: str) -> dict:
    # Pinned POST /users creates a NewUser magic link and requests an email.
    # The handler cannot attest SMTP delivery; never return 'email sent'.
    if provisioning_error():
        raise ValueError("Invitation provisioning unavailable")
    key = Path("/var/lib/briareus-platform/rauthy-users-invite.key").read_text().strip()
    if not key or not key.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ValueError("Provider key invalid")
    request = Request("http://briareus-rauthy:8080/auth/v1/users", method="POST",
        headers={"Authorization": "API-Key " + key, "Accept": "application/json", "Content-Type": "application/json"},
        data=json.dumps({"email": email, "language": "ru", "roles": [], "groups": None,
                         "given_name": None, "family_name": None, "user_expires": None}).encode())
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=3) as response:
        if response.status != 200 or response.headers.get_content_type() != "application/json":
            raise ValueError("Provider response invalid")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Provider response too large")
        result = json.loads(raw)
        if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not _ID.fullmatch(result["id"]):
            raise ValueError("Provider subject invalid")
        if result.get("email", "").casefold() != email.casefold() or result.get("roles") not in ([], ""):
            raise ValueError("Provider identity mismatch")
        return {"subject": result["id"]}


async def granted(tx, user_id) -> bool:
    row = await tx.scalar(select(OwnerAuditRow).where(
        OwnerAuditRow.action == "panel.inviter.set", OwnerAuditRow.object_id == str(user_id)
    ).order_by(OwnerAuditRow.created_at.desc(), OwnerAuditRow.id.desc()).limit(1))
    return row is not None and row.details.get("enabled") is True


async def execute_invitations(service, query, actor, deadline):
    from ._panel_management import ManagementError, fingerprint, identifier
    if query.action == "invitation.capabilities":
        if query.data:
            raise ManagementError(422, "COMMAND_FIELDS_INVALID")
        async with service.db.transaction() as tx:
            allowed = actor.role == "operator" or await granted(tx, actor.user_id)
            inviter_ids = []
            if actor.role == "operator":
                users = list(await tx.scalars(select(RauthyUserLinkRow).where(RauthyUserLinkRow.issuer == query.issuer).limit(101)))
                inviter_ids = [str(user.user_id) for user in users if await granted(tx, user.user_id)]
        return {"can_invite": allowed, "can_manage_inviters": actor.role == "operator",
                "inviter_ids": inviter_ids, "unavailable_reason": provisioning_error() if allowed else None}

    fields = {"inviter.set": {"user_id", "enabled"}, "invitation.issue": {"email"}}
    if query.action not in fields or set(query.data) != fields[query.action]:
        raise ManagementError(422, "COMMAND_FIELDS_INVALID")
    if query.action == "inviter.set" and type(query.data["enabled"]) is not bool:
        raise ManagementError(422, "COMMAND_FIELDS_INVALID")
    digest = fingerprint(query.model_dump(mode="json"))
    email = query.data.get("email")
    if query.action == "invitation.issue":
        if not isinstance(email, str) or not 3 <= len(email) <= 254 or email.count("@") != 1 or any(ord(c) < 33 or ord(c) > 126 for c in email):
            raise ManagementError(422, "EMAIL_INVALID")
        email = email.lower()
    lock_names = {"invitation:" + str(actor.user_id), str(query.operation_uuid)}
    if query.action == "inviter.set":
        lock_names.add("invitation:" + str(identifier(query.data["user_id"])))
    else:
        lock_names.add("invitation-email:" + email)
    async with service.db.transaction() as tx:
        for lock_name in sorted(lock_names):
            await tx.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": lock_name})
        link = await tx.get(RauthyUserLinkRow, actor.user_id, with_for_update=True)
        if link is None or not link.active or link.issuer != query.issuer:
            raise ManagementError(403, "INVITER_REQUIRED")
        operator = link.briareus_role == "operator"
        if query.action == "inviter.set" and not operator:
            raise ManagementError(403, "PLATFORM_OPERATOR_REQUIRED")
        if query.action == "invitation.issue" and not (operator or await granted(tx, actor.user_id)):
            raise ManagementError(403, "INVITER_REQUIRED")
        old = await tx.get(OwnerAuditRow, query.operation_uuid)
        if old:
            if old.actor_user_id != actor.user_id or old.details.get("fingerprint") != digest:
                raise ManagementError(409, "OPERATION_CONFLICT")
            if old.details.get("outcome", {}).get("state") not in {"provider_created", "committed"}:
                raise ManagementError(409, "INVITATION_OUTCOME_UNCONFIRMED")
            return old.details["outcome"]
        now = datetime.now(UTC)
        if now >= deadline:
            raise ManagementError(503, "PLATFORM_AUTHORITY_EXPIRED")
        if query.action == "inviter.set":
            target = await tx.get(RauthyUserLinkRow, identifier(query.data["user_id"]), with_for_update=True)
            if target is None or not target.active or target.issuer != query.issuer:
                raise ManagementError(404, "USER_NOT_FOUND")
            if datetime.now(UTC) >= deadline:
                raise ManagementError(503, "PLATFORM_AUTHORITY_EXPIRED")
            outcome = {"id": str(target.user_id), "enabled": query.data["enabled"], "state": "committed"}
            tx.add(OwnerAuditRow(id=query.operation_uuid, operation_uuid=query.operation_uuid,
                actor_user_id=actor.user_id, project_id=None, action="panel.inviter.set", object_id=str(target.user_id),
                owner_revision="panel-invitations-v1", details={"fingerprint": digest, "enabled": query.data["enabled"], "outcome": outcome}))
            tx.add(OwnerOutboxRow(operation_uuid=query.operation_uuid, event_name="panel.inviter.set", owner_revision="panel-invitations-v1", event_payload={"id": str(target.user_id)}))
            return outcome
        reason = provisioning_error()
        if reason:
            raise ManagementError(503, reason)
        # Reject existing provider identities; issuing an invitation must never
        # grant Platform membership just by guessing somebody else's email.
        existing = await service.provider.read_by_email(email=email)
        if existing.status == 200:
            raise ManagementError(409, "RAUTHY_ACCOUNT_ALREADY_EXISTS")
        if existing.status != 404:
            raise ManagementError(503, "RAUTHY_USER_LOOKUP_UNAVAILABLE")
        recent = await tx.scalar(select(OwnerAuditRow).where(OwnerAuditRow.action == "panel.invitation.issue",
            OwnerAuditRow.details["email"].astext == email).limit(1))
        if recent:
            raise ManagementError(409, "INVITATION_ALREADY_REQUESTED")
        tx.add(OwnerAuditRow(id=query.operation_uuid, operation_uuid=query.operation_uuid,
            actor_user_id=actor.user_id, project_id=None, action="panel.invitation.issue", object_id=str(query.operation_uuid),
            owner_revision="panel-invitations-v1", details={"fingerprint": digest, "email": email, "outcome": {"state": "issuing"}}))

    # Intent is durable BEFORE sending a non-idempotent vendor request.
    # Never retry a lost result and accidentally resend/rebind an account.
    try:
        provider_user = await asyncio.to_thread(create_provider_user, email)
    except Exception:
        raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED") from None
    fresh = await service.projection.resolve(issuer=query.issuer, subject=query.subject)
    if fresh is None or fresh.user_id != actor.user_id:
        raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED")
    async with service.db.transaction() as tx:
        row = await tx.get(OwnerAuditRow, query.operation_uuid, with_for_update=True)
        await tx.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"), {"key": "invitation:" + str(actor.user_id)})
        link = await tx.get(RauthyUserLinkRow, actor.user_id, with_for_update=True)
        if (datetime.now(UTC) >= min(deadline, fresh.expires_at) or link is None or not link.active
            or not (link.briareus_role == "operator" or await granted(tx, actor.user_id))):
            raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED")
        # Creating an invitation creates only the Rauthy account. Platform
        # membership is provisioned when that real user first signs in.
        outcome = {"id": provider_user["subject"], "state": "provider_created", "delivery": "unconfirmed"}
        row.details = {**row.details, "outcome": outcome}
        tx.add(OwnerOutboxRow(operation_uuid=query.operation_uuid, event_name="panel.invitation.issue",
            owner_revision="panel-invitations-v1", event_payload={"id": provider_user["subject"]}))
    return outcome
