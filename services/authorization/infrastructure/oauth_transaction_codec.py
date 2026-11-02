"""The pinned OAuth SDK document is encoded only at the repository boundary."""

from mcp.server.auth.provider import AuthorizationParams
from pydantic import AnyUrl

from authorization.domain.oauth_transaction import AuthorizationIntent


def authorization_intent(params: AuthorizationParams) -> AuthorizationIntent:
    return AuthorizationIntent(
        state=params.state,
        scopes=tuple(params.scopes) if params.scopes is not None else None,
        code_challenge=params.code_challenge,
        redirect_uri=str(params.redirect_uri),
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        resource=params.resource,
    )


def decode_intent(raw: str) -> AuthorizationIntent:
    return authorization_intent(AuthorizationParams.model_validate_json(raw))


def encode_intent(intent: AuthorizationIntent) -> str:
    return AuthorizationParams(
        state=intent.state,
        scopes=list(intent.scopes) if intent.scopes is not None else None,
        code_challenge=intent.code_challenge,
        redirect_uri=AnyUrl(intent.redirect_uri),
        redirect_uri_provided_explicitly=intent.redirect_uri_provided_explicitly,
        resource=intent.resource,
    ).model_dump_json()
