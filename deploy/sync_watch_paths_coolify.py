#!/usr/bin/env python3
"""Sync only Watch Paths on one exact, allowlisted Development Application.

The checked-in flat plan, scope allowlist and native Compose must agree before
credentials are read. Dry-run remains the default. No global discovery, resource
creation, environment-value reads, application starts or implicit deployment.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from watch_sync_application import SyncState, SyncWatchPaths
from watch_sync_domain import COOLIFY_ORIGIN, SyncError
from watch_sync_http import CoolifyWatchConfiguration
from watch_sync_sources import load_approved_target
from watch_sync_sources import read_watch_paths as read_watch_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose", required=True, type=Path, help="approved native Coolify Compose"
    )
    parser.add_argument("--application-uuid", required=True)
    parser.add_argument(
        "--branch", required=True, help="expected published Development branch main"
    )
    parser.add_argument("--coolify-url", required=True, help="exact approved Coolify HTTPS origin")
    parser.add_argument(
        "--apply", action="store_true", help="write only watch_paths; default read-only"
    )
    args = parser.parse_args()
    if args.coolify_url.rstrip("/") != COOLIFY_ORIGIN:
        raise SyncError("Coolify URL must be the exact approved Development instance origin")
    target = load_approved_target(
        Path(__file__).resolve().parents[1], args.compose, args.application_uuid, args.branch
    )
    print(f"Desired watch paths: {len(target.watch_paths)} for approved {target.identity.slug}")
    token = os.environ.get("COOLIFY_API_TOKEN", "")
    if not token:
        print("DRY RUN: no COOLIFY_API_TOKEN; no remote state checked or changed")
        return 2 if args.apply else 0
    result = SyncWatchPaths(CoolifyWatchConfiguration(target, token)).execute(
        target, apply=args.apply
    )
    messages = {
        SyncState.ALREADY_SYNCHRONIZED: "ALREADY SYNCHRONIZED: no change",
        SyncState.DIFFERENT: "DRY RUN: target matched; saved Watch Paths differ",
        SyncState.SYNCHRONIZED: "SYNCHRONIZED: watch_paths applied and verified",
    }
    print(messages[result.state])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (SyncError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
