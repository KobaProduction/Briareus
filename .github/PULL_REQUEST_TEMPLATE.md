<!-- Briareus V1 source PR template; use the corresponding branch's policy for V2 -->

## Owner and scope

Which of Core, Services, Hands, Shared or Operations owns the change? List affected consumers and associated issues.

## Source and runtime implications

Describe changed interfaces, persistence, identity/permissions, configuration, migration risk and deployment boundary. Is a Coolify variable, Watch Path, volume or live acceptance required?

## Validation

- [ ] Relevant owner tests and static checks passed against the actual proposed revision.
- [ ] Generated catalog, Dockerfile/Compose and dependency locks remain synchronized where affected.
- [ ] Database-specific checks (SQLite/PostgreSQL) and UI/build checks completed where relevant.
- [ ] Mandatory hooks, CI requirements and remote branch protections respected.
- [ ] Runtime/consumer acceptance and rollback requirements are stated separately from source tests.

## Documentation

- [ ] Current owner documentation under `docs/core`, `docs/services`, `docs/hands` or `docs/operations` was updated if the contract changed.
- [ ] No obsolete Management, Curl MCP, Legacy deployment or V2 behavior was introduced into active V1 instructions.
