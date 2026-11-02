"""Lazy public authority interface for the independently packaged SVC Hand."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .authorization import (
        ProjectAccessDenied,
        ProjectAccessPort,
        ProjectAction,
        ProjectInvocation,
        ProjectOperationScope,
        ProjectPermit,
        ProjectRuntimeAuthority,
        canonical_request_fingerprint,
    )

_EXPORT_MODULE: dict[str, str] = {
    "ProjectAccessDenied": "authorization",
    "ProjectAccessPort": "authorization",
    "ProjectAction": "authorization",
    "ProjectInvocation": "authorization",
    "ProjectOperationScope": "authorization",
    "ProjectPermit": "authorization",
    "ProjectRuntimeAuthority": "authorization",
    "canonical_request_fingerprint": "authorization",
}


def __getattr__(name: str) -> object:
    target = _EXPORT_MODULE.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{target}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORT_MODULE))


__all__ = [
    "ProjectAccessDenied",
    "ProjectAccessPort",
    "ProjectAction",
    "ProjectInvocation",
    "ProjectOperationScope",
    "ProjectPermit",
    "ProjectRuntimeAuthority",
    "canonical_request_fingerprint",
]
