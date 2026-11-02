"""One bounded browser reader for the existing three typed command models."""

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from ._http_errors import error_response


async def browser_command[CommandT: BaseModel](
    request: Request,
    command_type: type[CommandT],
    *,
    origin: str,
    maximum_bytes: int,
    origin_code: str,
    size_code: str,
    invalid_code: str,
) -> CommandT | JSONResponse:
    if (
        request.headers.getlist("origin") != [origin]
        or request.headers.getlist("content-type") != ["application/json"]
        or request.headers.get("sec-fetch-site") not in {None, "same-origin"}
    ):
        return error_response(403, origin_code)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum_bytes:
            return error_response(413, size_code)
    try:
        return command_type.model_validate_json(body)
    except ValidationError:
        return error_response(422, invalid_code)
