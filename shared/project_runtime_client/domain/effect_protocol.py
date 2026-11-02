"""Accepted owner database and phase identities for the private effect ABI."""

from typing import Literal

TargetOwner = Literal["resources", "files", "runtime", "reverse"]

EffectOwner = Literal["catalog", "files", "execution", "reverse"]
EffectPhase = Literal[
    "read",
    "list",
    "metadata",
    "file_dispatch",
    "file_reconcile",
    "reserve",
    "dispatch",
    "finalize",
    "inspect",
    "reconcile",
    "release",
    "claim",
    "cancel",
    "revoke",
    "open",
    "heartbeat",
    "queue_job",
    "start_job",
    "finish_job",
    "fail_job",
    "mark_unknown",
    "confirm_cleanup",
]
EffectState = Literal[
    "reserved",
    "dispatched",
    "unknown",
    "committed",
    "released",
    "active",
    "revoked",
    "closed",
    "running",
    "finished",
    "failed",
    "cancelled",
    "recorded",
    "absent",
]
_A11_TARGET: dict[EffectOwner, TargetOwner] = {
    "catalog": "resources",
    "files": "files",
    "execution": "runtime",
    "reverse": "reverse",
}

_DB: dict[
    EffectOwner,
    Literal["briareus_resources", "briareus_files", "briareus_runtime", "briareus_reverse"],
] = {
    "catalog": "briareus_resources",
    "files": "briareus_files",
    "execution": "briareus_runtime",
    "reverse": "briareus_reverse",
}
_PHASES: dict[EffectOwner, frozenset[EffectPhase]] = {
    "catalog": frozenset({"read", "inspect", "reserve", "revoke", "mark_unknown", "reconcile"}),
    "files": frozenset(
        {
            "read",
            "list",
            "metadata",
            "file_dispatch",
            "file_reconcile",
            "reserve",
            "dispatch",
            "finalize",
            "inspect",
            "reconcile",
            "release",
            "mark_unknown",
        }
    ),
    "execution": frozenset(
        {
            "open",
            "heartbeat",
            "queue_job",
            "start_job",
            "finish_job",
            "fail_job",
            "inspect",
            "revoke",
            "mark_unknown",
            "confirm_cleanup",
        }
    ),
    "reverse": frozenset({"claim", "dispatch", "inspect", "reconcile", "cancel", "mark_unknown"}),
}
