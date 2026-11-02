"""Typed FastAPI caller dependency shared by legacy route families."""

from typing import Protocol

from fastapi import Request

from authorization._project_access import CallerPrincipal


class VerifiedCallerDependency(Protocol):
    async def __call__(self, request: Request) -> CallerPrincipal: ...
