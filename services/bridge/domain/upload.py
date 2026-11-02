"""Validate bounded upload content before the independently authorized write."""

import base64
import binascii
import hashlib

from bridge.domain.project_dispatch import ProjectGatewayDispatchUnavailable


def decoded_upload(encoded: str, *, size_bytes: int, sha256: str) -> bytes:
    try:
        body = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ProjectGatewayDispatchUnavailable("PROJECT_UPLOAD_ENCODING_INVALID") from exc
    if len(body) != size_bytes or hashlib.sha256(body).hexdigest() != sha256:
        raise ProjectGatewayDispatchUnavailable("PROJECT_UPLOAD_CHECKSUM_INVALID")
    return body
