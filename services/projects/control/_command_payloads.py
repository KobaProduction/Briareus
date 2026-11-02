"""Exact signed Control command parameters; no runtime coercion or new wire fields."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MovePersonalToTeamPayload:
    team_id: str


@dataclass(frozen=True, slots=True)
class WithdrawTeamProjectPayload:
    """The original signed empty withdrawal body."""


@dataclass(frozen=True, slots=True)
class PrepareProjectDeletePayload:
    confirmed: bool


@dataclass(frozen=True, slots=True)
class ConfirmProjectDeletePayload:
    fenced_control_revision: int


@dataclass(frozen=True, slots=True)
class CreateAgentPayload:
    name: str
    parent_agent_id: str | None
