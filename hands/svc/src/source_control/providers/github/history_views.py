"""Git commit identity and signature observations projected from provider documents."""

from pydantic import BaseModel


class ActorSource(BaseModel):
    login: str | None = None
    id: int | None = None
    type: str | None = None


class IdentitySource(BaseModel):
    name: str | None = None
    email: str | None = None
    date: str | None = None


class VerificationSource(BaseModel):
    verified: bool | None = None
    reason: str | None = None
    verified_at: str | None = None
    signature: str | None = None
    payload: str | None = None


class CommitActor(BaseModel):
    login: str | None
    id: int | None
    type: str | None


class CommitIdentity(CommitActor):
    name: str
    email: str
    date: str


class CommitVerification(BaseModel):
    verified: bool
    reason: str
    verified_at: str | None
    signature_present: bool
    payload_present: bool


class CommitVerificationMaterial(CommitVerification):
    signature: str | None
    payload: str | None


class CommitSummary(BaseModel):
    sha: str
    message: str
    author: CommitIdentity
    committer: CommitIdentity
    verification: CommitVerification
    parents: list[str]
