# External ZITADEL access-token verification

Verifies asymmetric JWT access tokens against the configured issuer JWKS with PyJWT. The project audience and project-qualified `access` role bind grants to the configured organization. This single provider-managed project assignment grants full panel and MCP access; there is no per-surface permission matrix. This module never issues tokens or keeps local user sessions. Request the project audience scope and `urn:zitadel:iam:org:projects:roles`; configure ZITADEL applications to issue JWT access tokens. The browser public client and MCP public clients must be pre-registered in the Briareus project.

Dependencies: `PyJWT[crypto]>=2.10,<3`, Pydantic, Pydantic Settings, environment-models, environment-parsing, json-values.
