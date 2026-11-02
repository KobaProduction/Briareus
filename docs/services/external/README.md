# Infrastructure external services

Use the existing allowlisted External Services application for infrastructure
PostgreSQL, Valkey and private Rauthy. Its exact identity/scope is defined in
[Development access policy](../../operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
Do not create another Rauthy app or assume any database/volume is disposable.

Rauthy owns human identity, credentials/MFA and token issuance. Cedar belongs
to Node Access, not this vendor stack or infrastructure identity service.
Node-local SQLite/PostgreSQL/KV dependencies are separate Node-owned storage,
not a reason to repurpose the infrastructure owner databases.

## Provider configuration

Use the pinned upstream image and its supported native configuration. The
owning module supplies Compose, dependencies/configuration and source inputs.
Qualify real Base/Compose/Watch rather than inferring saved paths from docs.
Watch only this module and actual consumed shared packages.

Preserve protected existing bindings for TZ, PostgreSQL and Valkey. The
pinned configuration maps protected references to Rauthy native variables:

| Protected reference | Rauthy native input |
| --- | --- |
| RAUTHY_HIQLITE_RAFT_SECRET | HQL_SECRET_RAFT |
| RAUTHY_HIQLITE_API_SECRET | HQL_SECRET_API |
| RAUTHY_ENCRYPTION_KEY | ENC_KEYS |

The active key identifier and formats must match the actual pinned provider/
Compose contract. Preserve keys protecting existing encrypted state; rotation
requires qualified provider support and migration. Operators supply protected
values; agents do not inspect or print plaintext secrets.

Proxy/issuer/client/audience/callback configuration must describe real
registered endpoints and approved networking. Do not infer a new issuer,
wildcard trusted proxy or provider permission from a source example.
Native Control Plane UI → backend → private Rauthy is the human flow;
do not expose hosted provider login or arbitrary management passthrough.

## Initialization and data

Rauthy alone initializes/migrates its isolated storage and creates the initial
administrator on a genuinely empty provider. Operators use the supported
protected initial-credential procedure and sign in through Control Plane.
No registration link or first-visitor administrator assignment is implemented
by Briareus; services do not scrape initial passwords into other secrets.

Preserve existing PostgreSQL/Valkey/Rauthy data, volumes, keys and accounts.
An unused source path, new image or clean schema expectation does not
authorize wiping/recreating volumes or bootstrapping a populated provider.
Infrastructure owners perform only their migrations, never a global owner
reset or shared migrator. Do not point Rauthy at another owner's tables.

Honor the provider's configured MFA policy and supported continuations.
MFA-required is not successful login; unsupported protocol is unavailable,
not a reason to bypass provider checks. Configuration changes require the
same approved scope and qualified rollout as other provider changes.

## Acceptance

Follow source-first work and separately user-authorized testing. Qualify
actual saved settings, provider startup/storage, issuer/discovery/JWKS,
native login/challenges, identity token use and restart persistence.
Health/image success alone is not accepted identity or Node session access.

Official provider references:
[bootstrap](https://sebadob.github.io/rauthy/config/bootstrap.html),
[encryption](https://sebadob.github.io/rauthy/config/encryption.html) and
[storage/HA](https://sebadob.github.io/rauthy/config/ha.html).

See [identity/access](../../architecture/identity-and-session-access.md) and
[rollout](../../operations/development-rollout.md).
