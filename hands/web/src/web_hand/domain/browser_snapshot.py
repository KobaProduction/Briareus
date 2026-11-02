"""Only bounded public origins and visible text may leave an owned browser."""

from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True, slots=True)
class BrowserSnapshotRequest:
    bearer: str
    project_id: UUID
    agent_session_id: UUID
    grant_revision: int
    browser_handle: str
    max_text_chars: int


@dataclass(frozen=True, slots=True)
class BrowserSnapshot:
    origin: str
    title: str
    visible_text: str


def _safe_text(value: object, limit: int, *, multiline: bool) -> bool:
    if not isinstance(value, str) or len(value) > limit:
        return False
    allowed = "\t\r\n" if multiline else ""
    return all(ord(character) >= 32 or character in allowed for character in value)


def require_public_snapshot(value: object, max_chars: int) -> BrowserSnapshot:
    if not isinstance(value, BrowserSnapshot):
        raise ValueError("snapshot port returned an untrusted payload")
    origin = urlsplit(value.origin)
    if (
        origin.scheme != "https"
        or not origin.hostname
        or origin.username is not None
        or origin.password is not None
        or value.origin != f"{origin.scheme}://{origin.netloc}"
        or len(value.origin) > 240
        or not _safe_text(value.title, 160, multiline=False)
        or not _safe_text(value.visible_text, max_chars, multiline=True)
    ):
        raise ValueError("browser snapshot exceeds public safe contract")
    return value
