"""Provider-persisted PR choice; it records intent, never grants merge authority."""

import re

_MARKER = re.compile(r"<!-- briareus:source-branch-after-merge=(keep|delete) -->")


def branch_choice(body: str) -> bool | None:
    values = set(_MARKER.findall(body))
    return next(iter(values)) == "delete" if len(values) == 1 else None


def with_branch_choice(body: str, delete_source_branch_after_merge: bool) -> str:
    if type(delete_source_branch_after_merge) is not bool:
        raise ValueError("Explicit keep/delete source branch choice required")
    clean = _MARKER.sub("", body).rstrip()
    choice = "delete" if delete_source_branch_after_merge else "keep"
    return (
        clean + ("\n\n" if clean else "") + f"<!-- briareus:source-branch-after-merge={choice} -->"
    )
