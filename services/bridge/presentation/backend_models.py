"""Existing discovery and call wire fields, with named result contracts."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from operator import is_
from typing import Literal

from pydantic import BaseModel, Field

_missing: Callable[[str | None], bool] = partial(is_, None)


class BackendView(BaseModel):
    name: str
    public_path: str
    purpose: str
    status: Literal["available", "not_available"]
    tool_count: int
    error_type: str | None = Field(default=None, exclude_if=_missing)


class BackendDirectoryView(BaseModel):
    status: Literal["ok"] = "ok"
    backends: tuple[BackendView, ...]
    count: int


class BackendCallFailure(BaseModel):
    backend: str
    tool: str
    status: Literal["error"] = "error"
    error_type: str
    message: str
    hint: str
