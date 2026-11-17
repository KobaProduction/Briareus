# ADR 0003: V1 core services and optional MCP Hands

**Status: Accepted for the V1 source contract.** Live deployment/consumer acceptance remains a separate check.

## Context

The old monolithic MCP Bridge and scattered separate Files, Terminal, Curl and Management descriptions created unclear source ownership, coupled service restarts and conflicting runbooks. The newer V2 architecture has different Node/session/access requirements and must not be conflated with the current V1 rollout.

## Decision

1. Maintain **four core resources**: Control Panel UI, Control Panel API, Gateway and Dependencies.
2. Maintain **eleven optional MCP Hands** in the current source catalog, each owning its runtime, Compose, lock, tests and build inputs. Catalog membership is distinct from actual deployment/availability.
3. Keep account administration, encrypted credentials, audit, PostgreSQL/Alembic and selected SQLite local/test backend inside Control Panel API; no standalone Management.
4. Combine files, terminal and jobs in Server; browser in Playwright; keep source-control, analysis and read-only telemetry Hands separate. No Curl or root aggregate MCP application.
5. Use an external identity provider, independent Gateway MCP resource routes, shared in-process discovery and per-node access role.
6. Document owners under [Core](../core/README.md), [Services](../services/README.md), [Hands](../hands/README.md), [Operations](../operations/README.md). The manifest is the authoritative resource inventory.

## Consequences

A change to a Hand does not automatically restart the control plane or Dependencies. Live Coolify Watch Paths, resource revisions and end-to-end acceptance must be separately verified. Historical migrations remain explicitly non-operative; V2 decisions stay on V2.
