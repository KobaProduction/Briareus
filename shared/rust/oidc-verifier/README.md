# Shared Rust external OIDC resource verifier

`briareus-oidc-verifier-rs` verifies externally issued asymmetric JWT access
tokens or (when explicitly configured) opaque access tokens through RFC 7662
introspection. It enforces exact issuer/audience, required node role and
client identity, timestamps, signatures/JWKS in JWT mode and active status
in introspection mode. Keys/metadata and opaque-token principal caches are
bounded, short-lived; opaque-token cache identifiers are SHA-256 digests.
It never issues tokens, stores refresh tokens or owns user accounts.

The JWT implementation currently lacks Python's ES512 verification option;
ES512 configuration is explicitly rejected rather than silently weakened.
Signed JWT and opaque-token scenarios are compared with Python's verifier on
synthetic local issuers. This is a shared library, not a deployment.
