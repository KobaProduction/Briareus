# Briareus git

This leaf owns the `briareus_git` module.

Consumers: github, gitlab.

Its deployment watch is `shared/git/**`. Category directories are not
source packages or broad deployment watches. Service configuration fields live
with their service/capability; dependencies contain no imports from this module.

## Provider contracts

Both source-control Hands consume the same capability layer:

- `accounts.py`: revision-aware client caching and public-account projection.
- `provider_tools.py`: shared MCP registrations and structural interfaces for
  account, checkout, issue and repository operations.
- `local_transport.py`: one local Git authorization and publication engine,
  including credential storage, remote/account binding and one bounded refresh.
- `collaboration.py`: shared issue payloads, comment validation and review-thread
  pagination/mutation contracts.
- `ci.py`: shared job-log, incomplete-run retry and cancellation contracts.
- `files.py`: structural repository-file interface, text/base64 encoding,
  binary results with byte length and SHA-256.
- `tags.py`: structural tag interface and common MCP registration, with
  normalized tag names and commit IDs.
- `downloads.py`: bounded, credential-free public HTTPS redirect downloads,
  with DNS/IP checks and TLS hostname verification.
- `workflow_guard.py`: common local-first middleware and mutation policy;
  each provider supplies its own tool groups and instructions.

REST/GraphQL endpoints, account resolution, provider-native review and CI
models, and provider-side authorization stay in their respective Hands.
The common layer never substitutes its own permission for provider permission.
