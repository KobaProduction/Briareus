"""Shared Platform Control commands; state adapters remain layout-local."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents._persistence import AgentIdentityRow
from common.owner_contracts import SignedOwnerProofs, VerifiedOwnerOperation, require_signed_payload
from common.owner_transactions import OwnerCommandOutcome, OwnerLocalCommandExecutor
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, InvalidInput
from projects._persistence import ProjectRow
from projects.application.owner_receipts import ControlCreateAgent
from projects.control._command_payloads import (
    CreateAgentPayload,
)
from teams._persistence import TeamMembershipRow, TeamRow


@dataclass(frozen=True, slots=True)
class VerifiedProjectDeleteImpact:
    owner: Literal["resources", "files", "runtime", "reverse"]
    project_id: UUID
    fenced_control_revision: int
    zero_active_effects: bool
    observed_at: datetime
    receipt_digest: str


class TrustedProjectDeleteImpactPort(Protocol):
    async def verify_current_impact(
        self,
        *,
        project_id: UUID,
        fenced_control_revision: int,
        owner: Literal["resources", "files", "runtime", "reverse"],
    ) -> VerifiedProjectDeleteImpact:
        """Signed owner-state attestation; MUST reject stale Control fences."""
        ...


class ControlSourceService(ABC):
    def __init__(
        self,
        database: PlatformDatabase,
        commands: OwnerLocalCommandExecutor,
        *,
        delete_impact: TrustedProjectDeleteImpactPort | None = None,
    ) -> None:
        if database.engine.url.database != "briareus_platform" or commands.owner != "platform":
            raise RuntimeError("Control service cannot use a shared or foreign database")
        self.database = database
        self.commands = commands
        self.delete_impact = delete_impact

    @staticmethod
    async def _current_deletion_impacts(
        delete_impact: TrustedProjectDeleteImpactPort,
        decision: VerifiedOwnerOperation,
        fenced_control_revision: int,
    ) -> tuple[VerifiedProjectDeleteImpact, ...]:
        verified: list[VerifiedProjectDeleteImpact] = []
        for owner in ("resources", "files", "runtime", "reverse"):
            try:
                import asyncio

                async with asyncio.timeout(3):
                    receipt = await delete_impact.verify_current_impact(
                        project_id=decision.request.project_id,
                        fenced_control_revision=fenced_control_revision,
                        owner=owner,
                    )
            except Exception:
                raise AccessDenied("all durable deletion owner receipts must be current") from None
            receipt_candidate: object = receipt
            if (
                not isinstance(receipt_candidate, VerifiedProjectDeleteImpact)
                or receipt.owner != owner
                or receipt.project_id != decision.request.project_id
                or receipt.fenced_control_revision != fenced_control_revision
                or not receipt.zero_active_effects
                or receipt.observed_at.tzinfo is None
                or receipt.observed_at > datetime.now(UTC)
                or datetime.now(UTC) - receipt.observed_at > timedelta(seconds=20)
                or len(receipt.receipt_digest) != 64
                or any(c not in "0123456789abcdef" for c in receipt.receipt_digest)
            ):
                raise AccessDenied("owner deletion impact not signed at current fence")
            verified.append(receipt)
        return tuple(verified)

    @staticmethod
    async def _authorized_member(
        tx: AsyncSession, decision: VerifiedOwnerOperation, project: ProjectRow
    ) -> bool:
        if project.lifecycle_status != "active":
            return False
        actor = decision.request.caller_user_id
        if decision.actor_role == "superuser":
            return True
        if project.owner_user_id is not None:
            return project.owner_user_id == actor
        if project.owner_team_id is None:
            return False
        member = await tx.scalar(
            select(TeamMembershipRow.id)
            .where(
                TeamMembershipRow.team_id == project.owner_team_id,
                TeamMembershipRow.user_id == actor,
                TeamMembershipRow.active.is_(True),
            )
            .with_for_update()
        )
        return member is not None

    async def create_agent(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        name: str,
        parent_agent_id: UUID | None = None,
    ) -> OwnerCommandOutcome[ControlCreateAgent]:
        if (
            decision.request.operation != "agent.create"
            or not (1 <= len(name.strip()) <= 255)
            or (parent_agent_id is not None and parent_agent_id.version != 4)
        ):
            raise InvalidInput("invalid AgentIdentity command")
        require_signed_payload(
            decision.request,
            asdict(
                CreateAgentPayload(
                    name=name.strip(),
                    parent_agent_id=str(parent_agent_id) if parent_agent_id else None,
                )
            ),
        )

        async def mutate(tx: AsyncSession) -> ControlCreateAgent:
            project = await self._project(tx, decision)
            if not await self._authorized_member(tx, decision, project):
                raise AccessDenied("Project membership revoked")
            if parent_agent_id is not None:
                parent = await tx.get(AgentIdentityRow, parent_agent_id)
                if parent is None or parent.project_id != project.id or not parent.enabled:
                    raise AccessDenied("parent AgentIdentity is not active in this Project")
            row = AgentIdentityRow(
                id=uuid4(),
                project_id=project.id,
                parent_agent_id=parent_agent_id,
                name=name.strip(),
                enabled=True,
                version=1,
            )
            tx.add(row)
            project.resource_revision += 1
            return ControlCreateAgent(
                agent_id=str(row.id),
                project_id=str(project.id),
                resource_revision=project.resource_revision,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutate,
            event="agent.created",
            target=str(decision.request.project_id),
            response_model=ControlCreateAgent,
        )

    @staticmethod
    async def _require_project_owner(
        tx: AsyncSession, decision: VerifiedOwnerOperation, row: ProjectRow
    ) -> None:
        if decision.actor_role == "superuser":
            return
        actor = decision.request.caller_user_id
        if row.owner_user_id is not None:
            if row.owner_user_id == actor:
                return
            raise AccessDenied("only personal Project owner may prepare deletion")
        if row.owner_team_id is None:
            raise AccessDenied("Project has no verified current owner")
        team = await tx.scalar(
            select(TeamRow).where(TeamRow.id == row.owner_team_id).with_for_update()
        )
        member = await tx.scalar(
            select(TeamMembershipRow.id)
            .where(
                TeamMembershipRow.team_id == row.owner_team_id,
                TeamMembershipRow.user_id == actor,
                TeamMembershipRow.active.is_(True),
            )
            .with_for_update()
        )
        if team is None or team.owner_user_id != actor or member is None:
            raise AccessDenied("only current active Team owner may delete Team Project")

    @staticmethod
    @abstractmethod
    async def _project(tx: AsyncSession, decision: VerifiedOwnerOperation) -> ProjectRow:
        """Read and lock the selected layout's current Project state."""
        raise NotImplementedError
