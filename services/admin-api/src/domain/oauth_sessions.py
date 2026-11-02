from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OAuthSessionObservation:
    client_id: str
    client_name: str
    resource: str
    login: str
    subject: str
    scopes: tuple[str, ...]
    status: str
    event: str
    access_jti: str
    refresh_jti: str
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    occurred_at: datetime
    error_type: str
    error_message: str


@dataclass
class OAuthSession:
    id: str
    client_id: str
    client_name: str = ""
    resource: str = ""
    login: str = ""
    subject: str = ""
    scopes: list[str] = field(default_factory=list)
    status: str = "active"
    last_event: str = ""
    access_jti: str = ""
    refresh_jti: str = ""
    previous_refresh_jti: str = ""
    access_expires_at: datetime | None = None
    refresh_expires_at: datetime | None = None
    last_used_at: datetime | None = None
    last_refresh_at: datetime | None = None
    revoked_at: datetime | None = None
    error_type: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def observe(self, observation: OAuthSessionObservation) -> None:
        self._observe_identity(observation)
        self._observe_tokens(observation)
        self._observe_status(observation)

    def _observe_identity(self, observation: OAuthSessionObservation) -> None:
        if observation.client_id:
            self.client_id = observation.client_id
        if observation.client_name:
            self.client_name = observation.client_name
        if observation.resource:
            self.resource = observation.resource
        if observation.login:
            self.login = observation.login
        if observation.subject:
            self.subject = observation.subject
        if observation.scopes:
            self.scopes = list(observation.scopes)

    def _observe_tokens(self, observation: OAuthSessionObservation) -> None:
        if observation.access_jti:
            self.access_jti = observation.access_jti
        if observation.refresh_jti and observation.refresh_jti != self.refresh_jti:
            self.previous_refresh_jti = self.refresh_jti
            self.refresh_jti = observation.refresh_jti
        if observation.access_expires_at is not None:
            self.access_expires_at = observation.access_expires_at
        if observation.refresh_expires_at is not None:
            self.refresh_expires_at = observation.refresh_expires_at

    def _observe_status(self, observation: OAuthSessionObservation) -> None:
        self.status = observation.status
        self.last_event = observation.event
        self.updated_at = observation.occurred_at
        successful_refresh = observation.event.startswith(("refresh_success", "refresh_replay"))
        if observation.event in {"authorized", "access_used"} or successful_refresh:
            self.last_used_at = observation.occurred_at
        if successful_refresh:
            self.last_refresh_at = observation.occurred_at
        if observation.event == "revoked":
            self.revoked_at = observation.occurred_at
        if observation.error_type or observation.error_message:
            self.error_type = observation.error_type
            self.error_message = observation.error_message
        elif observation.status == "active":
            self.error_type = ""
            self.error_message = ""
