# Shared Rust external OIDC resource verifier

`briareus-oidc-verifier-rs` verifies externally issued asymmetric JWT access
tokens or (when explicitly configured) opaque access tokens through RFC 7662
introspection. It enforces exact issuer/audience, required node role and
client identity, timestamps, signatures/JWKS in JWT mode and active status
in introspection mode. Keys/metadata and opaque-token principal caches are
bounded, short-lived; opaque-token cache identifiers are SHA-256 digests.
It never issues tokens, stores refresh tokens or owns user accounts.

The configured asymmetric allowlist matches Python: RS256, RS384, RS512,
ES256, ES384, ES512 and EdDSA (Ed25519). The existing JWT SDK verifies six
algorithms; ES512 uses AWS-LC P-521/SHA-512 verification with fixed-width
JOSE coordinates and signatures. All access
token modes share issuer, audience, timestamp, client and node-role checks.
Synthetic issuers provide independent signatures, key-policy denials and
JWKS rotation tests. This is a shared library, not a deployment.
