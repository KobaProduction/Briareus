# External OpenID Connect access-token verification

Verifies asymmetric JWT access tokens against the configured issuer discovery document and JWKS. Issuer, API audience, organization and the explicitly configured node role determine access. `OIDC_REQUIRED_ROLE` is required and has no fallback: for example, the Tambov API and Gateway both require `tambov`; another node requires its own role. A role for another node or the former global `access` role does not authorize Tambov. Assigning multiple node roles allows access to those nodes only.

Identity providers own users, role assignments and sessions. This module never issues tokens or creates local user sessions. Role claims can be standard lists or organization-scoped project grants. Provider-specific project scopes and JWT access-token settings belong in the identity provider configuration.

Dependencies: `PyJWT[crypto]>=2.10,<3`, Pydantic, Pydantic Settings, environment-models, environment-parsing, json-values.
