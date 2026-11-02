"""Canonical keyed request digest with a named private-value wire tag.

Pydantic only adapts supported values to the input of the existing JSON
encoder. Python mode preserves typed fields and tuples; UUID/date
serializers preserve the original str/isoformat text rather than changing
the durable fingerprint format.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import partial
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    PlainSerializer,
    SecretBytes,
    SecretStr,
    SerializationInfo,
    TypeAdapter,
)
from pydantic_core import PydanticSerializationError, PydanticSerializationUnexpectedValue


@dataclass(frozen=True, slots=True)
class FingerprintContext:
    secret: bytes = field(repr=False)


class PrivateHmacTag(BaseModel):
    digest: str = Field(serialization_alias="__private_hmac_v1__")


def _secret_value(value: object) -> SecretStr | SecretBytes:
    if not isinstance(value, (SecretStr, SecretBytes)):
        raise ValueError("private canonical request value required")
    return value


def _private_tag(
    value: SecretStr | SecretBytes,
    info: SerializationInfo[FingerprintContext],
) -> PrivateHmacTag:
    if not isinstance(value, (SecretStr, SecretBytes)):
        raise PydanticSerializationUnexpectedValue("private canonical request value required")
    context = info.context
    raw = (
        value.get_secret_value().encode("utf-8")
        if isinstance(value, SecretStr)
        else value.get_secret_value()
    )
    return PrivateHmacTag(digest=hmac.new(context.secret, raw, hashlib.sha256).hexdigest())


def _uuid_text(value: UUID) -> str:
    if not isinstance(value, UUID):
        raise PydanticSerializationUnexpectedValue("UUID canonical request value required")
    return str(value)


def _iso_date(value: date) -> str:
    if not isinstance(value, date):
        raise PydanticSerializationUnexpectedValue("date canonical request value required")
    return value.isoformat()


type FingerprintScalar = (
    str
    | int
    | float
    | bool
    | Annotated[UUID, PlainSerializer(_uuid_text, return_type=str)]
    | Annotated[date, PlainSerializer(_iso_date, return_type=str)]
    | Annotated[datetime, PlainSerializer(_iso_date, return_type=str)]
    | Annotated[
        SecretStr | SecretBytes,
        BeforeValidator(_secret_value),
        PlainSerializer(_private_tag, return_type=PrivateHmacTag),
    ]
    | None
)
_FINGERPRINT_SCALARS = TypeAdapter[FingerprintScalar](FingerprintScalar)


def canonical_fingerprint(
    request: BaseModel,
    *,
    secret: bytes,
    mode: Literal["python", "json"] = "python",
) -> str:
    if not isinstance(request, BaseModel):
        raise TypeError("a typed command request is required")
    try:
        # The concrete request owns its fields. JSON's native encoder traverses
        # that serialization; only non-JSON scalars need the SDK serializer.
        encoded = json.dumps(
            request.model_dump(mode=mode, warnings="error"),
            default=partial(
                _FINGERPRINT_SCALARS.dump_python,
                mode="python",
                by_alias=True,
                context=FingerprintContext(secret),
                warnings="error",
            ),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    except PydanticSerializationError:
        # Unsupported request values must not be echoed alongside secrets.
        raise TypeError("unsupported canonical request field type") from None
    return hmac.new(secret, encoded, hashlib.sha256).hexdigest()
