#!/usr/bin/env python3
"""Print the historical checked-in bootstrap plan using local source only.

Remote bootstrap is retired: Development permits only the existing approved
project, environment and fourteen exact Application UUIDs. This command does
not reconcile them or establish deployment acceptance.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bootstrap_plan import LocalBootstrapPlan
from bootstrap_sources import read_local_plan


class BootstrapError(RuntimeError):
    """The requested operation exceeds local planning authority."""


def print_local_plan(plan: LocalBootstrapPlan) -> None:
    print(
        f"LOCAL SOURCE PLAN: {len(plan.applications)} historical registry Applications, "
        f"branch={plan.branch}"
    )
    for app in plan.applications:
        print(
            f"  {app.name}: base={app.base_directory} "
            f"required_inputs={','.join(app.required_inputs) or '-'}"
        )
        if app.bindings:
            bindings = ", ".join(
                binding.name + "=" + binding.reference
                for binding in sorted(app.bindings, key=lambda item: item.name)
            )
            print(f"  SHARED BINDINGS {app.name} (names/scopes only): {bindings}")
    print("LOCAL PLAN ONLY: no credentials read, no remote state checked or changed.")
    print("Use the existing exact-UUID Development workflow for approved configuration changes.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True, help="reviewed published Git branch/ref")
    parser.add_argument("--apply", action="store_true", help="retired; always rejected")
    parser.add_argument("--coolify-url", help="retired remote option; always rejected")
    parser.add_argument("--expected-version", help="retired remote option; always rejected")
    args = parser.parse_args()
    if args.apply or args.coolify_url is not None or args.expected_version is not None:
        raise BootstrapError(
            "remote bootstrap is retired; "
            "global resource reads and resource creation are forbidden; "
            "use the existing exact-UUID Development configuration workflow"
        )
    print_local_plan(read_local_plan(Path(__file__).resolve().parent, args.branch))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BootstrapError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
