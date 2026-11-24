"""Common collaboration contracts; native IDs and API state transitions stay in adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from briareus_json_values import JsonObject, JsonValue
from fastmcp import FastMCP
from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class IssueFields:
    body_key: str
    state_key: str
    state_values: dict[str, str]
    encode_labels: Callable[[list[str]], JsonValue]


def issue_payload(
    fields: IssueFields,
    *,
    title: str | None,
    body: str | None,
    state: str | None,
    labels: list[str] | None,
    error: type[Exception],
) -> JsonObject:
    payload: JsonObject = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload[fields.body_key] = body
    if state is not None:
        if state not in fields.state_values:
            raise error("state must be open or closed")
        payload[fields.state_key] = fields.state_values[state]
    if labels is not None:
        payload["labels"] = fields.encode_labels(labels)
    if not payload:
        raise error("no issue fields were supplied")
    return payload


def comment_payload(body: str, error: type[Exception]) -> JsonObject:
    if not body.strip():
        raise error("comment body must not be empty")
    return {"body": body}


def require_comment_deletion(comment_id: int, confirm: bool, error: type[Exception]) -> None:
    if type(comment_id) is not int or comment_id <= 0:
        raise error("comment ID must be a positive integer")
    if confirm is not True:
        raise error("deleting a comment requires confirm=true")


def validate_thread_page(number: int, per_page: int, error: type[Exception]) -> None:
    if number < 1:
        raise error("review request number must be positive")
    if not 1 <= per_page <= 100:
        raise error("per_page must be between 1 and 100")


def validate_thread_target(number: int, thread_id: str, error: type[Exception]) -> None:
    if number < 1 or not thread_id.strip():
        raise error("a positive review request number and a thread ID are required")


class ReviewThreadProvider(Protocol):
    def list_review_threads(
        self, repository: str, number: int, per_page: int, cursor: str | None, /
    ) -> JsonObject: ...

    def set_review_thread_resolved(
        self, repository: str, number: int, thread_id: str, resolved: bool, /
    ) -> JsonObject: ...


def register_review_thread_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], ReviewThreadProvider],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    provider: str,
) -> None:
    @mcp.tool(title=f"{provider} list review threads", annotations=read_annotations)
    def list_review_threads(
        account_id: str,
        repository: str,
        number: int,
        per_page: int = 100,
        cursor: str | None = None,
    ) -> JsonObject:
        """List one page of review discussions. Pass next_cursor to continue.

        The thread and comment details retain provider-native fields.
        """
        return client_factory(account_id).list_review_threads(repository, number, per_page, cursor)

    @mcp.tool(title=f"{provider} set review thread resolved", annotations=write_annotations)
    def set_review_thread_resolved(
        account_id: str,
        repository: str,
        number: int,
        thread_id: str,
        resolved: bool,
    ) -> JsonObject:
        """Resolve or reopen a discussion belonging to the explicit PR/MR."""
        return client_factory(account_id).set_review_thread_resolved(
            repository, number, thread_id, resolved
        )
