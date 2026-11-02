"""Human node configuration never grants execution or changes project authority."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, NamedTuple
from uuid import UUID


class NodeConflict(ValueError):
    pass


class NodeInvalid(ValueError):
    pass


class NodeForbidden(ValueError):
    pass


class NodeMissing(ValueError):
    pass


class NodeSourceUnavailable(ValueError):
    pass


class NodeReceiptUnavailable(ValueError):
    pass


type NodeScopeKind = Literal["personal", "team", "shared"]
type NodeMutationKind = Literal["register", "rename", "disable"]


@dataclass(frozen=True)
class NodeActor:
    actor_uuid: UUID
    project_owner_kind: Literal["user", "team"] | None
    project_owner_uuid: UUID | None


@dataclass(frozen=True)
class OperatorSelector:
    issuer: str
    subject: str
    actor_uuid: UUID
    project_uuid: UUID
    identity_expires_at: datetime

    def require_current(self, now: datetime) -> None:
        if not current_lease(self.identity_expires_at, now):
            raise NodeForbidden("Current project identity required")


@dataclass(frozen=True)
class OperatorEvidence:
    issuer: str
    subject: str
    actor_uuid: str
    project_uuid: str
    permissions: tuple[str, ...]
    role: str
    expires_at: datetime
    project_owner_kind: Literal["user", "team"] | None
    project_owner_uuid: UUID | None


class OperatorAuthority(NamedTuple):
    actor: NodeActor
    expires_at: datetime


def current_lease(expiry: datetime, now: datetime) -> bool:
    return expiry.tzinfo is not None and now < expiry <= now + timedelta(seconds=30)


def attest_operator(
    selector: OperatorSelector, evidence: OperatorEvidence, now: datetime
) -> OperatorAuthority:
    if (
        evidence.issuer != selector.issuer
        or evidence.subject != selector.subject
        or evidence.actor_uuid != str(selector.actor_uuid)
        or evidence.project_uuid != str(selector.project_uuid)
        or evidence.role != "operator"
        or "use_resources" not in evidence.permissions
        or not current_lease(evidence.expires_at, now)
    ):
        raise NodeForbidden("Current Platform operator required")
    actor = NodeActor(selector.actor_uuid, evidence.project_owner_kind, evidence.project_owner_uuid)
    return OperatorAuthority(actor, min(selector.identity_expires_at, evidence.expires_at))


@dataclass(frozen=True)
class NodeCapacity:
    memory_bytes: int
    cpu_millis: int
    pids: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (self.memory_bytes, self.cpu_millis, self.pids)
        ):
            raise NodeInvalid("Positive node capacity required")


@dataclass(frozen=True)
class NodeBudget:
    total: NodeCapacity
    reserved: NodeCapacity

    def __post_init__(self) -> None:
        if (
            self.reserved.memory_bytes >= self.total.memory_bytes
            or self.reserved.cpu_millis >= self.total.cpu_millis
            or self.reserved.pids >= self.total.pids
        ):
            raise NodeInvalid("Control/runtime reserve must leave execution capacity")


@dataclass(frozen=True)
class NewNode:
    id: UUID
    name: str
    scope: NodeScopeKind
    owner_uuid: UUID | None
    host_uuid: UUID
    runtime_uid: int
    endpoint: str
    budget: NodeBudget

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", node_name(self.name))

    def require_owner(self, actor: NodeActor) -> None:
        permitted = (
            self.owner_uuid is None
            if self.scope == "shared"
            else self.owner_uuid == actor.actor_uuid
            if self.scope == "personal"
            else actor.project_owner_kind == "team"
            and self.owner_uuid is not None
            and self.owner_uuid == actor.project_owner_uuid
        )
        if not permitted:
            raise NodeForbidden("Node owner must match current Platform scope")


@dataclass(frozen=True)
class ManagedNode:
    id: UUID
    name: str
    scope: NodeScopeKind
    owner_uuid: UUID | None
    host_uuid: UUID
    runtime_uid: int
    endpoint: str
    budget: NodeBudget
    enabled: bool
    paired: bool
    sequence: int
    last_seen_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class NodeCommandIdentity:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    action: NodeMutationKind
    fingerprint: str
    expected_sequence: int | None


@dataclass(frozen=True)
class ChangeNode:
    node_uuid: UUID
    sequence: int
    name: str
    action: Literal["rename", "disable"]


def node_name(value: str) -> str:
    name = value.strip()
    if not name or any(ord(character) < 32 for character in name):
        raise NodeInvalid("Printable node name required")
    return name
