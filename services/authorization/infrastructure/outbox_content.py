"""Bind an outbox claim to its complete native JSONB document, without exporting it."""

import hashlib

from authorization.infrastructure.journal_records import AccessOutboxEvent
from runtime_peer import canonical_json


def outbox_content_sha256(document: AccessOutboxEvent) -> str:
    encoded = canonical_json(document.model_dump(mode="json", exclude_unset=True))
    return hashlib.sha256(b"authorization-outbox-content-v1\0" + encoded).hexdigest()
