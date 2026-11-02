"""One thin signed HTTP adapter; runtime authority/use cases live inward."""

import logging
from typing import Protocol

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from authorization.application.runtime_dispatch import DispatchRuntime, RuntimeRequest
from authorization.domain.runtime_policy import (
    RuntimeAccessDenied,
    RuntimeIdentity,
    RuntimeIdentityRequired,
)
from authorization.presentation.runtime_protocol import RuntimeAccessCommand, runtime_response
from common.platform_errors import AccessDenied, Conflict, IdempotencyConflict, InvalidInput

logger = logging.getLogger(__name__)


class RuntimeFactory(Protocol):
    def for_request(self, request: Request) -> DispatchRuntime | None: ...


class RuntimeController:
    def __init__(self, factory: RuntimeFactory) -> None:
        self._factory = factory

    async def access(self, command: RuntimeAccessCommand, request: Request) -> JSONResponse:
        dispatcher = self._factory.for_request(request)
        if dispatcher is None:
            raise HTTPException(503, "Access owner not ready")
        if request.scope.get("briareus.service_peer") != "briareus:control-panel-api":
            raise HTTPException(403, "Human management peer required")
        try:
            result = await dispatcher.execute(
                RuntimeRequest(
                    RuntimeIdentity(
                        command.issuer,
                        command.subject,
                        command.actor_uuid,
                        command.project_uuid,
                        command.identity_expires_at,
                    ),
                    command.action,
                    command.command,
                )
            )
            return runtime_response(result)
        except RuntimeIdentityRequired:
            raise HTTPException(401, "Current human identity required") from None
        except (AccessDenied, RuntimeAccessDenied) as error:
            logger.warning(
                "private Access command denied action=%s reason=%s", command.action, error
            )
            return self._error(403, "PROJECT_ACCESS_DENIED")
        except (Conflict, IdempotencyConflict):
            return self._error(409, "REVISION_CONFLICT")
        except (InvalidInput, ValidationError, ValueError):
            return self._error(422, "SCOPE_INVALID")
        except OSError:
            return self._error(503, "RESOURCE_OWNER_UNAVAILABLE")

    @staticmethod
    def _error(status: int, code: str) -> JSONResponse:
        return JSONResponse({"error": {"code": code}}, status_code=status)
