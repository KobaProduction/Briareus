"""Adapt the existing event wire format without leaking Pydantic into domain values."""

from domain.telemetry import Invocation
from pydantic import ConfigDict, RootModel

from common.account_contracts import InvocationEvent


class InvocationDocument(RootModel[Invocation]):
    model_config = ConfigDict(strict=True, frozen=True)


def invocation_from_event(event: InvocationEvent) -> Invocation:
    return Invocation(
        request_id=event.request_id,
        module=event.module,
        tool=event.tool,
        account_id=event.account_id,
        provider=event.provider,
        status=event.status,
        duration_ms=event.duration_ms,
        error_type=event.error_type,
        arguments_json=event.arguments_json,
        result_json=event.result_json,
        error_message=event.error_message,
    )
