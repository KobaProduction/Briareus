"""Durable local operation phases, not a second Core desired-state authority."""
from __future__ import annotations

import fcntl
import os
import sqlite3
import json
from datetime import UTC, datetime
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from node_protocol import Deployment
from node_protocol.diagnostics import diagnostic_wire

TERMINAL = frozenset({"succeeded", "failed"})


class OperationConflict(RuntimeError):
    pass


class Journal:
    def __init__(self, path: Path):
        self.listeners = set()
        self.lock = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.lock)
            raise OperationConflict("Only one controller may own this journal") from None
        self.db = sqlite3.connect(path, isolation_level=None, timeout=3)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS operations (
              id TEXT PRIMARY KEY, placement TEXT NOT NULL, sequence INTEGER NOT NULL,
              desired TEXT NOT NULL, fingerprint TEXT NOT NULL, phase TEXT NOT NULL,
              previous TEXT, container TEXT, error TEXT,
              UNIQUE(placement, sequence)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_placement_operation
              ON operations(placement) WHERE phase NOT IN ('succeeded','failed');
            CREATE TABLE IF NOT EXISTS applied (
              placement TEXT PRIMARY KEY, spec TEXT NOT NULL, container TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS configuration (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), sequence INTEGER NOT NULL,
              record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mcp_admissions (
              request TEXT PRIMARY KEY, expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS node_events (
              cursor INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
              payload TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)
        if "diagnostic" not in {row[1] for row in self.db.execute("PRAGMA table_info(operations)")}:
            self.db.execute("ALTER TABLE operations ADD COLUMN diagnostic TEXT")

    def close(self):
        self.db.close()
        os.close(self.lock)

    def failed_candidate(self, desired, container, fingerprint, before_sequence):
        row=self.db.execute("SELECT desired FROM operations WHERE placement=? AND container=? "
            "AND fingerprint=? AND sequence<? AND phase='failed' ORDER BY sequence DESC LIMIT 1",
            (str(desired.id),container,fingerprint,before_sequence)).fetchone()
        if row is None:
            return False
        prior=Deployment.model_validate_json(row["desired"])
        return (prior.node_uuid==desired.node_uuid and prior.project_uuid==desired.project_uuid
            and prior.release.module==desired.release.module
            and prior.workspace==desired.workspace)

    def configuration(self):
        row = self.db.execute("SELECT sequence,record FROM configuration WHERE singleton=1").fetchone()
        return dict(row) if row else None

    def matches_applied(self, desired, container):
        row = self.db.execute("SELECT spec,container FROM applied WHERE placement=?", (str(desired.id),)).fetchone()
        return bool(row and row["container"] == container
                    and Deployment.model_validate_json(row["spec"]).fingerprint == desired.fingerprint)

    def forward_target(self, proof):
        import time
        row = self.db.execute("SELECT spec,container FROM applied WHERE placement=?",
                              (str(proof.placement_uuid),)).fetchone()
        latest = self.db.execute("SELECT phase,error FROM operations WHERE placement=? "
            "ORDER BY sequence DESC LIMIT 1", (str(proof.placement_uuid),)).fetchone()
        if not row or (latest and (latest["phase"] not in TERMINAL or latest["error"] == "ROLLBACK_FAILED")):
            raise OperationConflict("Placement is unavailable or updating")
        spec = Deployment.model_validate_json(row["spec"])
        if (not spec.enabled or spec.node_uuid != proof.node_uuid or spec.project_uuid != proof.project_uuid
            or spec.fingerprint != proof.fingerprint or spec.release.module != proof.module
            or spec.release.port != proof.port or proof.expires_at <= time.time()):
            raise OperationConflict("Forwarding proof does not match the applied placement")
        return row["container"]

    def admit_forward(self, proof):
        import time
        with self.transaction():
            container = self.forward_target(proof)
            self.db.execute("DELETE FROM mcp_admissions WHERE expires_at<=?", (int(time.time()),))
            if self.db.execute("SELECT COUNT(*) FROM mcp_admissions").fetchone()[0] >= 10000:
                raise OperationConflict("MCP admission window is full")
            try:
                self.db.execute("INSERT INTO mcp_admissions VALUES (?,?)",
                                (str(proof.request_uuid), proof.expires_at))
            except sqlite3.IntegrityError:
                raise OperationConflict("MCP request already admitted; effects are never retried") from None
        return container

    def configure(self, sequence: int, record):
        if type(sequence) is not int or not 1 <= sequence < 2**63:
            raise OperationConflict("Valid node configuration sequence required")
        with self.transaction():
            previous = self.configuration()
            wire = record.model_dump_json()
            if previous and (sequence < previous["sequence"] or (
                sequence == previous["sequence"] and wire != previous["record"])):
                raise OperationConflict("Stale or conflicting node configuration")
            self.db.execute("INSERT INTO configuration VALUES (1,?,?) ON CONFLICT(singleton) "
                            "DO UPDATE SET sequence=excluded.sequence,record=excluded.record", (sequence, wire))
            if previous is None or previous["record"] != wire or previous["sequence"] != sequence:
                self.event("configuration", {"node_uuid":str(record.id),"enabled":record.enabled,"sequence":sequence})

    @contextmanager
    def transaction(self):
        if self.db.in_transaction:
            yield
            return
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
            for listener in tuple(self.listeners):
                listener.set()
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def event(self, topic, payload):
        with self.transaction():
            row = self.db.execute("INSERT INTO node_events(topic,payload,created_at) VALUES (?,?,?)",
                (topic,json.dumps(payload,separators=(",",":")),datetime.now(UTC).isoformat()))
            self.db.execute("DELETE FROM node_events WHERE cursor<=?", (row.lastrowid-2048,))

    def events_after(self, cursor):
        if type(cursor) is not int or not 0 <= cursor < 2**63:
            raise OperationConflict("Bounded event cursor required")
        first,last=self.db.execute("SELECT MIN(cursor),MAX(cursor) FROM node_events").fetchone()
        if (first and cursor < first-1) or cursor > (last or 0):
            raise OperationConflict("Event replay window lost; obtain authoritative inventory")
        return [dict(row) for row in self.db.execute(
            "SELECT * FROM node_events WHERE cursor>? ORDER BY cursor LIMIT 128",(cursor,))]

    def event_cursor(self):
        return self.db.execute("SELECT COALESCE(MAX(cursor),0) FROM node_events").fetchone()[0]

    def get(self, operation: UUID):
        row = self.db.execute("SELECT * FROM operations WHERE id=?", (str(operation),)).fetchone()
        if row is None:
            return None
        value = dict(row)
        value["diagnostic"] = diagnostic_wire(json.loads(value["diagnostic"])) if value["diagnostic"] else None
        return value

    def reserve(self, operation: UUID, sequence: int, desired: Deployment):
        if operation.version != 4 or type(sequence) is not int or not 1 <= sequence < 2**63:
            raise OperationConflict("Valid operation UUID and monotonic sequence required")
        with self.transaction():
            existing = self.get(operation)
            if existing:
                if (existing["desired"] != desired.model_dump_json()
                    or existing["sequence"] != sequence):
                    raise OperationConflict("Operation identity reused with different command")
                return existing
            latest = self.db.execute("SELECT MAX(sequence) FROM operations WHERE placement=?",
                                     (str(desired.id),)).fetchone()[0]
            if latest is not None and sequence <= latest:
                raise OperationConflict("Stale placement command")
            previous = self.db.execute("SELECT spec FROM applied WHERE placement=?",
                                       (str(desired.id),)).fetchone()
            try:
                self.db.execute("INSERT INTO operations (id,placement,sequence,desired,fingerprint,phase,previous,container,error) "
                    "VALUES (?,?,?,?,?,'queued',?,NULL,NULL)",
                    (str(operation), str(desired.id), sequence, desired.model_dump_json(),
                     desired.fingerprint, previous[0] if previous else None))
            except sqlite3.IntegrityError:
                raise OperationConflict("Another placement operation is active") from None
            self.event("operation", {"operation_uuid":str(operation),"sequence":sequence,"phase":"queued","error":None})
        return self.get(operation)

    def phase(self, operation: UUID, phase: str, *, container=None, error=None, diagnostic=None):
        allowed = {"queued", "pulling", "stopping", "creating", "checking", "rolling_back", *TERMINAL}
        if phase not in allowed or (error is not None and error not in {
            "UPDATE_FAILED", "ROLLBACK_FAILED", "CONTROLLER_INTERRUPTED", "UNMANAGED_INSTANCE",
        }):
            raise ValueError("Bounded operation state required")
        with self.transaction():
            previous=self.get(operation)
            if previous is None:
                raise OperationConflict("Operation not found")
            details = previous["diagnostic"] or (diagnostic_wire(diagnostic) if diagnostic is not None else None)
            self.db.execute("UPDATE operations SET phase=?,container=COALESCE(?,container),error=?,diagnostic=? WHERE id=?",
                            (phase, container, error, json.dumps(details) if details else None, str(operation)))
            if previous["phase"]!=phase or previous["error"]!=error or previous["diagnostic"]!=details:
                payload = {"operation_uuid":str(operation),"sequence":previous["sequence"],"phase":phase,"error":error}
                if details is not None:
                    payload["diagnostic"] = details
                self.event("operation", payload)

    def applied(self, operation: UUID, spec: Deployment, container_id: str):
        with self.transaction():
            self.restore(spec, container_id)
            self.phase(operation, "succeeded", container=container_id)

    def restore(self, spec: Deployment, container_id: str):
        self.db.execute("INSERT INTO applied VALUES (?,?,?) ON CONFLICT(placement) DO UPDATE "
                        "SET spec=excluded.spec,container=excluded.container",
                        (str(spec.id), spec.model_dump_json(), container_id))
