from __future__ import annotations

import logging

from common.identity_provider import IdentityProviderError, ZitadelClient
from control_panel_api.application.identity import pkce_challenge
from control_panel_api.domain.identity import IdentityGrant, LoginTransaction

logger = logging.getLogger(__name__)


class ZitadelPanelIdentity:
    def __init__(self, client: ZitadelClient, public_origin: str) -> None:
        self.client = client
        self.public_origin = public_origin
        self.callback_url = public_origin + "/api/auth/callback"

    def authorization_url(self, transaction: LoginTransaction) -> str:
        return self.client.authorization_url(
            callback_url=self.callback_url,
            state=transaction.state,
            nonce=transaction.nonce,
            challenge=pkce_challenge(transaction.verifier),
        )

    def exchange(self, code: str, transaction: LoginTransaction) -> IdentityGrant:
        login = self.client.exchange_code(
            code=code,
            callback_url=self.callback_url,
            verifier=transaction.verifier,
            nonce=transaction.nonce,
        )
        return IdentityGrant(
            login.identity.sub,
            login.identity.iss,
            login.identity.display_name,
            login.expires_at,
            login.access_token,
            login.id_token,
            login.refresh_token,
        )

    def logout(self, grant: IdentityGrant) -> str:
        return_url = self.public_origin + "/admin/"
        try:
            destination = self.client.logout_url(id_token=grant.id_token, return_url=return_url)
            self.client.revoke(grant.refresh_token or grant.access_token)
            return destination
        except IdentityProviderError:
            logger.warning("Local Control Panel session revoked; provider logout is unavailable")
            return return_url
