"""Identity of the accepted project authority revision."""

import re

_REVISION_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def valid_project_revision(value: object) -> bool:
    """Accepted A4 project_permit.decision_version SHA-256 hex identity."""
    return isinstance(value, str) and _REVISION_PATTERN.fullmatch(value) is not None
