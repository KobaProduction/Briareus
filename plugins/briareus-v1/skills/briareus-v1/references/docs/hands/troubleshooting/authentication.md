# ChatGPT MCP — OAuth refresh and Gateway 401 errors

**Owners:** [MCP OAuth](../../oauth-chatgpt.md) and
[OIDC configuration](../../oidc.md). The Gateway is a resource server;
it does **not** store ChatGPT connector refresh tokens or perform their
rotation. A private Hand success does not prove the MCP client is authorized.

## ChatGPT says internal error, but Gateway saw no request

[Issue #555](https://github.com/KobaProduction/Briareus/issues/555)
records observed failures for Playwright and GitHub: ChatGPT returned
`internal error`, no corresponding request reached Gateway, and ZITADEL
rejected refresh with `OIDCS-28ubl` / `OIDCSession.RefreshTokenInvalid`,
HTTP 400. For investigated ZITADEL v4.20.0, this code indicates a
presented refresh-token ID different from the stored ID, **not** the
ordinary expiration code. A direct private GitHub call succeeded.

**Do not invent the cause:** concurrent refresh rotation, a lost client
persist of a successful refresh response and issuer session mismatch
were hypotheses in that issue. Sharing a public OAuth client ID does
not prove two MCP connections share one particular grant.

**Triage:** correlate the client's UTC failure window, the issuer's
nonsecret error category and Gateway ingress. If Gateway did not receive
a request, do **not** restart the Hand to fix client token refresh.
Reauthorize the *affected* MCP connection if needed, then verify a fresh
call **from ChatGPT**. Repeated failures should be tracked with bounded
sanitized evidence, not token content.

## Request reaches Gateway but is rejected

Use the [Gateway's fixed failure categories](../../oauth-chatgpt.md),
not raw JWT payloads. `expired` means no valid token arrived in time;
it does not prove whether client, issuer or storage failed renewal.
`invalid_audience` or `missing_grant` points elsewhere.
An OIDC administrator role does **not** automatically assign a Briareus
node role. Verify the selected node's actual configured issuer,
audience and project-qualified role **without** revealing bearer tokens.

## Unsafe shortcuts

Never disable rotation/reuse detection, accept old refresh tokens forever,
remove OAuth to avoid an error, change instance-wide token TTL based
on one event, or add a token broker without a reviewed threat model.
[Issue #555](https://github.com/KobaProduction/Briareus/issues/555)
owns the unresolved investigation and test expectations.

**Completion:** authenticated client call succeeds through the actual
ChatGPT connector; internal MCP and container health alone are insufficient.
