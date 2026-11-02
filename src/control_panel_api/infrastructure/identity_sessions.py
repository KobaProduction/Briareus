from __future__ import annotations

import json
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column, Engine, MetaData, String, Table, delete, select

from control_panel_api.domain.identity import IdentityGrant, LoginTransaction, PanelIdentitySession
from control_panel_api.infrastructure.crypto import FernetCredentialCipher


class TransactionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str
    verifier: str
    nonce: str
    expires_at: int


class GrantRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    issuer: str
    display_name: str
    expires_at: int
    access_token: str
    id_token: str
    refresh_token: str


class SessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identifier: str
    csrf_token: str
    grant: GrantRecord


class SqlIdentitySessionRepository:
    """Additional owner tables; existing Control Panel schema and data are untouched."""

    def __init__(self, engine: Engine, cipher: FernetCredentialCipher) -> None:
        self.engine = engine
        self.cipher = cipher
        metadata = MetaData()
        self.transactions = Table(
            "bri_identity_transactions",
            metadata,
            Column("identifier", String(128), primary_key=True),
            Column("payload", String, nullable=False),
        )
        self.sessions = Table(
            "bri_identity_sessions",
            metadata,
            Column("identifier", String(128), primary_key=True),
            Column("payload", String, nullable=False),
        )
        metadata.create_all(engine, checkfirst=True)

    def put_transaction(self, transaction: LoginTransaction) -> None:
        payload = self.cipher.encrypt(json.dumps(asdict(transaction)))
        with self.engine.begin() as connection:
            connection.execute(
                self.transactions.insert().values(identifier=transaction.state, payload=payload)
            )

    def consume_transaction(self, state: str) -> LoginTransaction | None:
        with self.engine.begin() as connection:
            row = connection.execute(
                delete(self.transactions)
                .where(self.transactions.c.identifier == state)
                .returning(self.transactions.c.payload)
            ).first()
        if row is None:
            return None
        item = TransactionRecord.model_validate_json(self.cipher.decrypt(row[0]))
        return LoginTransaction(item.state, item.verifier, item.nonce, item.expires_at)

    def put_session(self, session: PanelIdentitySession) -> None:
        payload = self.cipher.encrypt(json.dumps(asdict(session)))
        with self.engine.begin() as connection:
            connection.execute(
                self.sessions.insert().values(identifier=session.identifier, payload=payload)
            )

    def get_session(self, identifier: str) -> PanelIdentitySession | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(self.sessions.c.payload).where(self.sessions.c.identifier == identifier)
            ).first()
        if row is None:
            return None
        item = SessionRecord.model_validate_json(self.cipher.decrypt(row[0]))
        grant = IdentityGrant(
            item.grant.subject,
            item.grant.issuer,
            item.grant.display_name,
            item.grant.expires_at,
            item.grant.access_token,
            item.grant.id_token,
            item.grant.refresh_token,
        )
        return PanelIdentitySession(item.identifier, item.csrf_token, grant)

    def delete_session(self, identifier: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                delete(self.sessions).where(self.sessions.c.identifier == identifier)
            )
