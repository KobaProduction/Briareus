"""Prepare the exact four-field UI body before final authority revalidation."""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from control_panel_api._oidc_files_content import (
    BrowserFilesRead,
    _error,
    _json_body,
    _session_cookie,
)
from control_panel_api.application.files_read import (
    FilesReadDocument,
    FilesReadFailure,
    PreparedFilesRead,
    ReadFiles,
)
from control_panel_api.domain.files_read import FilesReadRequest
from control_panel_api.infrastructure.json_fields import validate_unique_fields

HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class FilesReadPreparation:
    def prepare(self, path: str, payload: bytes) -> PreparedFilesRead:
        document = FilesReadDocument(
            path,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            base64.b64encode(payload).decode("ascii"),
        )
        return PreparedFilesRead(
            document, bytes(JSONResponse(asdict(document), headers=HEADERS).body)
        )


@dataclass(frozen=True, slots=True)
class FilesReadController:
    use_case: Callable[[Request], ReadFiles]
    origin: str
    host: str

    async def read(self, request: Request) -> Response:
        data = await _json_body(request, origin=self.origin, host=self.host)
        if isinstance(data, JSONResponse):
            return data
        try:
            validate_unique_fields(data)
            body = BrowserFilesRead.model_validate_json(data)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return _error(422, "FILES_READ_REQUEST_INVALID")
        ticket = _session_cookie(request)
        if ticket is None:
            return _error(401, "FILES_READ_SESSION_REQUIRED")
        result = await self.use_case(request).execute(
            ticket,
            FilesReadRequest(
                body.project_uuid,
                body.agent_session_uuid,
                body.expected_grant_revision,
                body.path,
                body.max_bytes,
            ),
            request,
        )
        if isinstance(result, FilesReadFailure):
            return _error(result.status, result.code)
        return Response(result.wire, media_type="application/json", headers=HEADERS)
