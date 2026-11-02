"""Strict JSON-RPC request adaptation; no transport payload is an authority proof."""

import json
import re

from control_panel_api.application.panel_commands import PanelCommand, RpcRequest
from control_panel_api.domain.panel_protocol import (
    REALTIME_TOPICS,
    HistorySelection,
    TopicSelection,
)

from .panel_commands import decode_facade_command


def request_frame(raw: str, *, messages: int) -> RpcRequest:
    decoded: object = json.loads(raw)
    if not isinstance(decoded, dict) or messages > 20:
        raise ValueError("Invalid Panel request envelope")
    if set(decoded) != {"jsonrpc", "id", "method", "params"} or decoded["jsonrpc"] != "2.0":
        raise ValueError("Invalid Panel request envelope")
    identifier: object = decoded["id"]
    method: object = decoded["method"]
    params: object = decoded["params"]
    if not isinstance(identifier, str) or not 1 <= len(identifier) <= 64:
        raise ValueError("Invalid Panel request identifier")
    if not isinstance(method, str) or not isinstance(params, dict):
        raise ValueError("Invalid Panel request method")
    return RpcRequest(identifier, method, decode_command(method, params))


def decode_command(method: str, params: object) -> PanelCommand:
    if method in {"events.subscribe", "events.unsubscribe"}:
        return subscription(params)
    if method == "events.history":
        return history(params)
    if method in {"system.ping", "platform.current"}:
        return "empty" if not params else "unavailable"
    return decode_facade_command(method, params)


def cursor(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{1,16}-[0-9]{1,16}", value) is None:
        raise ValueError("Invalid Panel cursor")
    return value


def topics(value: object, *, nonempty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > len(REALTIME_TOPICS):
        raise ValueError("Invalid Panel topics")
    result: list[str] = []
    for topic in value:
        if not isinstance(topic, str) or topic not in REALTIME_TOPICS:
            raise ValueError("Invalid Panel topic")
        result.append(topic)
    if nonempty and not result:
        raise ValueError("Empty Panel topics")
    return tuple(result)


def subscription(params: object) -> TopicSelection:
    if not isinstance(params, dict) or set(params) - {"topic", "topics", "cursor"}:
        raise ValueError("Invalid subscription fields")
    requested = params.get("topics", [params.get("topic")])
    return TopicSelection(topics(requested, nonempty=False), cursor(params.get("cursor")))


def history(params: object) -> HistorySelection:
    if not isinstance(params, dict) or set(params) - {"topics", "before", "limit", "project_uuid"}:
        raise ValueError("Invalid history fields")
    limit = params.get("limit", 100)
    project = params.get("project_uuid")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid history limit")
    if project is not None and not isinstance(project, str):
        raise ValueError("Invalid history project")
    return HistorySelection(
        topics(params.get("topics", ["mcp.calls"]), nonempty=True),
        cursor(params.get("before")),
        limit,
        project,
    )


class DecodedPanelProtocol:
    def request(self, raw: str, messages: int) -> RpcRequest:
        return request_frame(raw, messages=messages)
