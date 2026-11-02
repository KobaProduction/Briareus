# Provider operations contract

Use only the existing allowlisted infrastructure vendor application in the
[Development scope](../../docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
Preserve PostgreSQL/Valkey/Rauthy state, volumes, keys, accounts and current
public contracts. No reset, extra provider app, rekey or plaintext secret
inspection follows from source/configuration work.

Control Plane backend privately integrates version-pinned Rauthy protocol/
management APIs and owns protected provider administration credentials and
sessions/challenges. UI and Node receive neither those private credentials
nor identity signing authority. There is no separate infrastructure
Authorization service. Rauthy retains identity signing and credential verification.
All human sign-in/MFA/recovery screens stay native Control Plane UI.

Rauthy owns initialization and the initial administrator on a genuinely
empty provider. Operators use its supported protected credential procedure.
Do not scrape initial passwords into other service databases/secrets,
rerun bootstrap against populated state or bypass required MFA.

Provider issuer/client/audience/callback/proxy/storage configuration must
describe actual approved endpoints and supported upstream behavior. Source
examples and a successful health probe are not accepted identity/permission.
Do not invent users, roles, issuer values or token success.

Node Access/Cedar independently owns local session/grant decisions and
autonomous Node state. Shared integration resource values are delivered into
Node storage; they are not Rauthy human passwords or signing keys.

Qualify provider startup/storage, real native challenges/tokens, intended
protocol-route exposure and restart persistence during the separately
authorized acceptance phase. Observe only exact scoped resources and keep
rollback. Ordinary publication follows local validation and mandatory hooks.

See [external requirements](../../docs/services/external/README.md),
[identity/access](../../docs/architecture/identity-and-session-access.md) and
[rollout](../../docs/operations/development-rollout.md).
