---
name: coolify-deployment-workflow
description: Work with Coolify applications, Compose, builds, logs, secrets and deployment acceptance using the authoritative AI Agent Workflow services-deployment skill.
---

# Briareus Coolify provider workflow

Read the shared build-synchronized skill at skill://ai-agent-services-deployment/SKILL.md before work. Its references include the upstream AI Agent Workflow AGENTS.md and services-deployment router. Read the relevant referenced modules completely; coolify-compose.md is mandatory when Coolify parses Compose. Do not assume that only the URI being advertised means the source files have been read.

1. Identify the specific Coolify account and project/resource scope using safe metadata tools. Verify required permissions. Do not infer approval to deploy from access to a read-only tool.
2. Separate Git desired state, Coolify parser/variables, container state, and real-consumer acceptance. Check source commit, saved Watch Paths, Compose location, runtime dependencies and actual resource state before proposing changes.
3. Treat variable values and runtime logs as sensitive. Do not disclose shared or locked values. A two-stage application-variable read still requires distinct operator approval.
4. Before deployment/restart, obtain authority for the exact application/service. A queued deploy is not completion; inspect deployment logs, state and consumer acceptance independently.
5. Reuse existing storage, networking, persistent data and operator keys. Do not replace running resources, rename ENV contracts or cross privileged boundaries by assumption.

The source skill is synchronized at image build. Offline deployments use the last built snapshot, not unverified current upstream content.
