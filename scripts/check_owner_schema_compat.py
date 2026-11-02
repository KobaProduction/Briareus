#!/usr/bin/env python3
"""Non-mutating source compatibility fence for exact deployed owner revisions.

This compares immutable Git sources and packaged migrations. It does not read a
live database or authorize a downgrade, stamp, data migration or reset.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from owner_schema_application import AssessOwnerSchema
from owner_schema_git import GitOwnerSources
from owner_schema_policy import OWNERS, CompatibilityState, OwnerAssessment, OwnerComparison


def inspect_owner(root: Path, *, owner: str, previous: str, candidate: str) -> OwnerAssessment:
    comparison = OwnerComparison(owner, previous, candidate)
    return AssessOwnerSchema(GitOwnerSources(root)).execute(comparison)


def print_assessment(data: OwnerAssessment) -> None:
    print(
        json.dumps(
            {
                "owner": data.comparison.owner,
                "previous_deployed_source_sha": data.comparison.previous,
                "candidate_source_sha": data.comparison.candidate,
                "previous_reviewed_versions": list(data.previous_history.reviewed or ()),
                "candidate_reviewed_versions": list(data.candidate_history.reviewed or ()),
                "previous_image_migrations": list(data.previous_history.packaged or ()),
                "historical_resources_layout_verified": data.previous_history.legacy_resources,
                "candidate_image_migrations": list(data.candidate_history.packaged or ()),
                "state": data.state,
                "findings": list(data.findings),
                "live_database_alembic_version_verified": False,
                "live_data_migration_authorized": False,
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", choices=sorted(OWNERS), required=True)
    parser.add_argument("--previous-deployed-sha", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    opts = parser.parse_args()
    try:
        data = inspect_owner(
            opts.repo,
            owner=opts.owner,
            previous=opts.previous_deployed_sha,
            candidate=opts.candidate_sha,
        )
    except (ValueError, OSError, subprocess.SubprocessError):
        print(
            json.dumps(
                {"state": "UNVERIFIED", "findings": ["invalid_exact_commit_or_read_failure"]}
            )
        )
        return 2
    print_assessment(data)
    return {
        CompatibilityState.COMPATIBLE: 0,
        CompatibilityState.INCOMPATIBLE: 1,
        CompatibilityState.UNVERIFIED: 2,
    }[data.state]


if __name__ == "__main__":
    raise SystemExit(main())
