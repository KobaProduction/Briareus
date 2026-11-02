"""Source Control Git process execution with provider-owned failure classes."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git_output(
    target: Path,
    *args: str,
    timeout_seconds: int,
    error_type: type[RuntimeError],
    env: dict[str, str] | None = None,
    allow_missing: bool = False,
) -> str:
    result = subprocess.run(  # noqa: S603 -- fixed Git argv in a validated owner workspace
        ["git", "-C", str(target), *args],  # noqa: S607 -- Git comes from the owner image PATH
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_seconds,
    )
    if allow_missing and result.returncode == 1 and not (result.stderr or result.stdout).strip():
        return ""
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2048:]
        raise error_type(f"git command failed with exit code {result.returncode}: {detail}")
    return (result.stdout or result.stderr).strip()
