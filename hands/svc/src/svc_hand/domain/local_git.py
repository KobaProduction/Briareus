"""Local Git identities and credential-free effect receipts."""

import re
from dataclasses import dataclass
from typing import Literal


def require_remote(remote: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", remote):
        raise ValueError("Explicit safe Git remote required")


def require_expected_sha(sha: str) -> None:
    if sha and not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
        raise ValueError("Expected remote SHA must be hexadecimal")


@dataclass(frozen=True)
class LocalGitAuthorization:
    repository: str
    workspace: str
    remote: str
    remote_url: str
    branch: str
    authorized: Literal[True] = True
    credential_storage: Literal["none"] = "none"
    push_mode: Literal["authorized_mcp_call"] = "authorized_mcp_call"
    requires_current_permission_per_push: Literal[True] = True


@dataclass(frozen=True)
class LocalGitPush:
    repository: str
    workspace: str
    remote: str
    branch: str
    head: str
    pushed: Literal[True] = True
    credential_storage: Literal["none"] = "none"


@dataclass(frozen=True)
class CheckoutRequest:
    mode: str = "snapshot"
    ref: str = ""
    branch: str = ""
    overwrite: bool = False

    def __post_init__(self) -> None:
        if self.mode not in {"git", "snapshot"}:
            raise ValueError("Supported checkout mode required")


@dataclass(frozen=True)
class CheckoutReceipt:
    path: str
    mode: str
    branch: str | None
    git_metadata: bool
    canonical_repository: str
    reused: bool
    ref: str | None
    credential_storage: Literal["none"] = "none"
