"""Existing no-store code-only HTTP failure serialization."""

from fastapi.responses import JSONResponse

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def error_response(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status, headers=_NO_STORE)
